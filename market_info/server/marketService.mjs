// Combines providers, cache and quota into normalized answers for the
// browser. Every quote and series carries its source, data time, known
// delay, and whether it is a stale copy.
import { MarketCache } from './cache.mjs';
import { RequestBudget } from './budget.mjs';
import { errors, MarketError } from './errors.mjs';
import { ALPHA_VANTAGE, fetchDailySeries } from './providers/alphaVantage.mjs';
import { COINGECKO, fetchMarkets, fetchMarketChart } from './providers/coinGecko.mjs';
import { STOCK_SYMBOL_RE, CRYPTO_TICKER_RE } from './config.mjs';
import { isStockSeriesOld, usMarketSession, nyDateKey } from './time.mjs';

const DAY_MS = 86400000;
const CRYPTO_OLD_AFTER_MS = 30 * 60000;
const CRYPTO_HISTORY_DAYS = 90;

// Only transient failures fall back to an older copy; a bad key or an
// unknown symbol is reported as is.
const TRANSIENT = new Set(['rate_limited', 'upstream_unavailable', 'network', 'bad_response']);

export function average(values) {
  const v = values.filter((x) => typeof x === 'number');
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

export function quoteFromBars(bars) {
  const last = bars.at(-1);
  const prev = bars.length > 1 ? bars.at(-2) : null;
  const change = prev ? last.close - prev.close : null;
  const window = bars.slice(-21, -1).map((b) => b.volume);
  return {
    price: last.close,
    previousClose: prev?.close ?? null,
    change,
    changePct: prev ? (change / prev.close) * 100 : null,
    volume: last.volume,
    avgVolume20: window.length >= 20 && window.every((v) => v !== null) ? average(window) : null,
  };
}

export function createMarketService({ config, fetchImpl = globalThis.fetch, cache = null, now = () => Date.now() }) {
  const store = cache ?? new MarketCache({ now });
  const avBudget = new RequestBudget({
    name: 'alpha_vantage', perMinute: config.alphaVantage.perMinute, perDay: config.alphaVantage.perDay, cache: store, now,
  });
  const cgBudget = new RequestBudget({
    name: 'coingecko', perMinute: config.coinGecko.perMinute, perMonth: config.coinGecko.perMonth, cache: store, now,
  });

  const cryptoBySymbol = new Map(config.crypto.map((c) => [c.symbol, c]));
  const stockBySymbol = new Map(config.stocks.map((s) => [s.symbol, s]));

  function resolve(raw) {
    const symbol = String(raw ?? '').trim().toUpperCase();
    if (cryptoBySymbol.has(symbol)) return { type: 'crypto', ...cryptoBySymbol.get(symbol) };
    if (STOCK_SYMBOL_RE.test(symbol)) {
      return { type: 'stock', symbol, name: stockBySymbol.get(symbol)?.name ?? symbol, configured: stockBySymbol.has(symbol) };
    }
    if (CRYPTO_TICKER_RE.test(symbol)) throw errors.invalidSymbol(symbol, COINGECKO.name);
    throw errors.badSymbolFormat(String(raw ?? '').slice(0, 20));
  }

  async function guarded(budget, provider, call) {
    const slot = budget.tryConsume();
    if (!slot.ok) throw errors.rateLimited(provider.name, slot.retryAfterSec, slot.scope !== 'provider');
    try {
      return await call();
    } catch (err) {
      if (err instanceof MarketError && err.code === 'rate_limited') budget.blockFor(err.retryAfterSec ?? 60);
      throw err;
    }
  }

  function requireKey(cfg, provider) {
    if (!cfg.apiKey) throw errors.notConfigured(provider.name, provider.keyEnv);
  }

  function metaFor(provider, result, asOf, extra = {}) {
    return {
      source: { id: provider.id, name: provider.name, url: provider.url, attribution: provider.attribution ?? null },
      delay: provider.delay,
      delayLabel: provider.delayLabel,
      asOf,
      fetchedAt: result.storedAt,
      fromCache: result.fromCache,
      stale: result.stale || Boolean(extra.old),
      staleReason: result.stale ? 'fetch_failed' : extra.old ? 'old_data' : null,
      warning: result.error ? result.error.message : null,
      ...extra,
    };
  }

  async function stockSeries(asset) {
    requireKey(config.alphaVantage, ALPHA_VANTAGE);
    const result = await store.getOrFetch(`av:daily:${asset.symbol}`, {
      ttlMs: config.ttl.stockMs,
      maxStaleMs: 7 * DAY_MS,
      fallbackOn: (e) => TRANSIENT.has(e.code),
      fetcher: () => guarded(avBudget, ALPHA_VANTAGE,
        () => fetchDailySeries(config.alphaVantage, asset.symbol, fetchImpl)),
    });
    const bars = result.value.bars;
    const last = bars.at(-1);
    const session = usMarketSession(now());
    const partial = session.state === 'open' && last.date === nyDateKey(now());
    return {
      result,
      bars,
      meta: metaFor(ALPHA_VANTAGE, result, last.t, {
        old: isStockSeriesOld(last.date, now()),
        partial,
        lastRefreshed: result.value.lastRefreshed,
        marketState: session.state,
        marketReason: session.reason,
        volumeLabel: 'נפח יומי (מספר מניות)',
        changeBasis: 'previous_close',
        candles: true,
      }),
    };
  }

  async function cryptoQuotes() {
    requireKey(config.coinGecko, COINGECKO);
    const ids = config.crypto.map((c) => c.id).sort();
    const result = await store.getOrFetch(`cg:markets:${ids.join(',')}`, {
      ttlMs: config.ttl.cryptoQuoteMs,
      maxStaleMs: DAY_MS,
      fallbackOn: (e) => TRANSIENT.has(e.code),
      // Map is not JSON-serializable; the cache keeps a plain object.
      fetcher: () => guarded(cgBudget, COINGECKO,
        async () => Object.fromEntries(await fetchMarkets(config.coinGecko, ids, fetchImpl))),
    });
    return result;
  }

  function cryptoQuoteFor(asset, result) {
    const q = result.value[asset.id];
    if (!q) throw errors.invalidSymbol(asset.symbol, COINGECKO.name);
    const old = q.asOf ? now() - q.asOf > CRYPTO_OLD_AFTER_MS : false;
    return {
      symbol: asset.symbol, displaySymbol: asset.symbol, name: q.name, type: 'crypto', currency: 'USD',
      price: q.price, previousClose: q.previousClose, change: q.change, changePct: q.changePct,
      volume: q.volume, avgVolume20: null,
      meta: metaFor(COINGECKO, result, q.asOf, {
        old, partial: false, marketState: 'open', marketReason: 'continuous',
        volumeLabel: 'נפח מסחר ב-24 השעות האחרונות (בדולרים)', changeBasis: '24h', candles: false,
        providerId: asset.id,
      }),
    };
  }

  async function quote(raw) {
    const asset = resolve(raw);
    if (asset.type === 'crypto') return cryptoQuoteFor(asset, await cryptoQuotes());
    const { bars, meta } = await stockSeries(asset);
    return {
      symbol: asset.symbol, displaySymbol: asset.symbol, name: asset.name, type: 'stock', currency: 'USD',
      ...quoteFromBars(bars), meta,
    };
  }

  async function history(raw) {
    const asset = resolve(raw);
    if (asset.type === 'stock') {
      const { bars, meta } = await stockSeries(asset);
      return { symbol: asset.symbol, bars: bars.map(({ date, ...b }) => b), meta };
    }
    requireKey(config.coinGecko, COINGECKO);
    const result = await store.getOrFetch(`cg:chart:${asset.id}:${CRYPTO_HISTORY_DAYS}`, {
      ttlMs: config.ttl.cryptoHistoryMs,
      maxStaleMs: 3 * DAY_MS,
      fallbackOn: (e) => TRANSIENT.has(e.code),
      fetcher: () => guarded(cgBudget, COINGECKO,
        () => fetchMarketChart(config.coinGecko, asset.id, CRYPTO_HISTORY_DAYS, fetchImpl)),
    });
    const bars = result.value.bars;
    return {
      symbol: asset.symbol,
      bars,
      meta: metaFor(COINGECKO, result, bars.at(-1).t, {
        old: now() - bars.at(-1).t > DAY_MS * 2,
        partial: true,
        marketState: 'open',
        volumeLabel: 'נפח 24 שעות (בדולרים)',
        candles: false,
        note: 'נקודה יומית אחת לכל יום (מחיר בלבד, ללא נרות). הנקודה האחרונה היא המחיר העדכני ביותר.',
      }),
    };
  }

  // Every configured asset, each with its own quote or error, so one failing
  // provider does not hide the other.
  async function assets() {
    const out = [];
    for (const s of config.stocks) {
      try { out.push(await quote(s.symbol)); } catch (err) {
        out.push({ symbol: s.symbol, displaySymbol: s.symbol, name: s.name, type: 'stock', currency: 'USD', error: toJson(err) });
      }
    }
    let cg = null;
    let cgError = null;
    if (config.crypto.length) {
      try { cg = await cryptoQuotes(); } catch (err) { cgError = err; }
    }
    for (const c of config.crypto) {
      try {
        if (cgError) throw cgError;
        out.push(cryptoQuoteFor(c, cg));
      } catch (err) {
        out.push({ symbol: c.symbol, displaySymbol: c.symbol, name: c.symbol, type: 'crypto', currency: 'USD', error: toJson(err) });
      }
    }
    return out;
  }

  function status() {
    const provider = (p, cfg, budget) => ({
      id: p.id, name: p.name, url: p.url, covers: p.covers, delay: p.delay, delayLabel: p.delayLabel,
      attribution: p.attribution ?? null, keyEnv: p.keyEnv, configured: Boolean(cfg.apiKey), usage: budget.snapshot(),
    });
    return {
      providers: {
        stocks: provider(ALPHA_VANTAGE, config.alphaVantage, avBudget),
        crypto: provider(COINGECKO, config.coinGecko, cgBudget),
      },
      sessions: { us: usMarketSession(now()), crypto: { state: 'open', reason: 'continuous' } },
      universe: { stocks: config.stocks.map((s) => s.symbol), crypto: config.crypto.map((c) => c.symbol) },
      cacheTtl: config.ttl,
      warnings: config.warnings,
      serverTime: now(),
    };
  }

  return { resolve, quote, history, assets, status };
}

export function toJson(err) {
  if (err instanceof MarketError) return err.toJSON();
  return { code: 'internal', message: 'שגיאה פנימית בשרת המקומי.' };
}
