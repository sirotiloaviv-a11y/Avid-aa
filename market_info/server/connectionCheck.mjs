// Connection check against the real providers. It fetches one price and one
// history per provider, verifies the response format the adapters assume,
// and reports source, data time and delay. Keys are never included in the
// report: they are only placed in request URLs / headers, and every text
// that could echo a request is passed through `redact`.
import { MarketError, errors } from './errors.mjs';
import { RequestBudget } from './budget.mjs';
import { ALPHA_VANTAGE, fetchDailySeries } from './providers/alphaVantage.mjs';
import { COINGECKO, fetchMarkets, fetchMarketChart } from './providers/coinGecko.mjs';
import { quoteFromBars } from './marketService.mjs';
import { isStockSeriesOld, lastCompletedSessionDate, usMarketSession } from './time.mjs';

// What the adapters assume about each provider. Written down because the
// official documentation could not be read while the adapters were built;
// the check marks each one confirmed or contradicted by a real answer.
export const ASSUMPTIONS = {
  alpha_vantage: {
    'av.json': 'התשובה היא JSON',
    'av.meta': 'קיים "Meta Data" עם "2. Symbol", "3. Last Refreshed" ו-"5. Time Zone"',
    'av.series': 'קיים "Time Series (Daily)" שמפתחותיו תאריכים בפורמט YYYY-MM-DD',
    'av.fields': 'כל שורה כוללת "1. open", "2. high", "3. low", "4. close", "5. volume" עם ערכים מספריים',
    'av.tz': 'אזור הזמן המדווח הוא US/Eastern (שעת סגירה 16:00 ניו יורק)',
    'av.compact': 'outputsize=compact מחזיר כ-100 ימי מסחר',
    'av.eod': 'הנתון האחרון הוא יום מסחר שהסתיים (סוף יום), לא מחיר תוך-יומי',
  },
  coingecko: {
    'cg.auth': 'מסלול Demo: כתובת בסיס https://api.coingecko.com/api/v3 וכותרת x-cg-demo-api-key מתקבלות',
    'cg.markets': '/coins/markets מחזיר מערך עם id, symbol, name, current_price, total_volume, price_change_24h, price_change_percentage_24h, last_updated',
    'cg.fresh': 'last_updated עדכני — השהיה של דקות ולא של שעות (עד 30 דקות)',
    'cg.chart': '/coins/{id}/market_chart עם days=90 ו-interval=daily מחזיר prices ו-total_volumes כזוגות [זמן במילישניות, ערך]',
    'cg.daily': 'נקודות ההיסטוריה יומיות (כ-91 נקודות ל-90 יום)',
  },
};

export function redact(text, secrets) {
  let out = String(text ?? '');
  for (const s of secrets.filter((x) => x && x.length >= 4)) out = out.split(s).join('***');
  return out.replace(/(apikey=)[^&\s"']+/gi, '$1***').replace(/(x-cg-demo-api-key["']?\s*[:=]\s*["']?)[^\s"',}]+/gi, '$1***');
}

class Tracker {
  constructor(providerId) {
    this.list = Object.entries(ASSUMPTIONS[providerId]).map(([id, text]) => ({ id, text, result: 'not_checked', note: '' }));
  }

  set(id, ok, note = '') {
    const a = this.list.find((x) => x.id === id);
    a.result = ok ? 'confirmed' : 'contradicted';
    a.note = note;
  }
}

const isNumStr = (v) => typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v));
const isPair = (p) => Array.isArray(p) && p.length === 2 && Number.isFinite(p[0]) && (p[1] === null || Number.isFinite(p[1]));

// A non-JSON error answer comes from the network path (proxy, firewall),
// not the provider, so it neither confirms nor contradicts any assumption.
const fromNetworkPath = (res) => res.body === null && res.status >= 400;

function inspectAlphaVantage(res, t) {
  if (fromNetworkPath(res)) return;
  t.set('av.json', res.body !== null, res.body === null ? `התקבל ${res.headers?.get?.('content-type') ?? 'תוכן לא ידוע'} (HTTP ${res.status})` : '');
  if (!res.body || typeof res.body !== 'object') return;
  if (res.body['Error Message'] || res.body.Note || res.body.Information) return; // an error answer says nothing about the data format
  const meta = res.body['Meta Data'];
  t.set('av.meta', Boolean(meta && '2. Symbol' in meta && '3. Last Refreshed' in meta && '5. Time Zone' in meta),
    meta ? `מפתחות: ${Object.keys(meta).join(', ')}` : 'חסר "Meta Data"');
  const series = res.body['Time Series (Daily)'];
  const dates = series && typeof series === 'object' ? Object.keys(series) : [];
  t.set('av.series', dates.length > 0 && dates.every((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)),
    series ? `${dates.length} תאריכים` : `מפתחות בתשובה: ${Object.keys(res.body).join(', ')}`);
  if (dates.length) {
    const keys = ['1. open', '2. high', '3. low', '4. close', '5. volume'];
    const bad = dates.filter((d) => !keys.every((k) => isNumStr(series[d]?.[k])));
    t.set('av.fields', bad.length === 0, bad.length ? `${bad.length} שורות חריגות, למשל ${bad[0]}: ${JSON.stringify(series[bad[0]])}` : '');
    t.set('av.compact', dates.length >= 90 && dates.length <= 110, `${dates.length} ימים`);
  }
  if (meta) t.set('av.tz', meta['5. Time Zone'] === 'US/Eastern', `התקבל: ${meta['5. Time Zone']}`);
}

function inspectMarkets(res, t) {
  if (fromNetworkPath(res)) return;
  if (res.status === 401 || res.status === 403) {
    t.set('cg.auth', false, `HTTP ${res.status} — ${JSON.stringify(res.body).slice(0, 160)}`);
    return;
  }
  if (res.status === 200) t.set('cg.auth', true);
  if (!Array.isArray(res.body)) return;
  const need = ['id', 'symbol', 'name', 'current_price', 'total_volume', 'price_change_24h', 'price_change_percentage_24h', 'last_updated'];
  const first = res.body[0] ?? {};
  const missing = need.filter((k) => !(k in first));
  t.set('cg.markets', res.body.length > 0 && missing.length === 0, missing.length ? `חסרים: ${missing.join(', ')}` : '');
}

function inspectChart(res, t) {
  if (fromNetworkPath(res)) return;
  if (res.status !== 200 || !res.body || typeof res.body !== 'object') {
    if (res.status >= 400) t.set('cg.chart', false, `HTTP ${res.status}${res.body ? ` — ${JSON.stringify(res.body).slice(0, 160)}` : ''}`);
    return;
  }
  const { prices, total_volumes: vols } = res.body;
  const ok = Array.isArray(prices) && prices.every(isPair) && Array.isArray(vols) && vols.every(isPair);
  t.set('cg.chart', ok, ok ? '' : `מפתחות בתשובה: ${Object.keys(res.body).join(', ')}`);
  if (Array.isArray(prices) && prices.length > 2) {
    const gaps = prices.slice(1, -1).map((p, i) => p[0] - prices[i][0]);
    const daily = gaps.every((g) => Math.abs(g - 86400000) < 3600000);
    t.set('cg.daily', daily, `${prices.length} נקודות${daily ? '' : '; המרווחים אינם יומיים'}`);
  }
}

function errorInfo(err, secrets) {
  if (err instanceof MarketError) return { code: err.code, message: redact(err.message, secrets) };
  return { code: 'internal', message: redact(err?.message ?? String(err), secrets) };
}

async function consume(budget, provider) {
  const slot = budget.tryConsume();
  if (!slot.ok) throw errors.rateLimited(provider.name, slot.retryAfterSec, slot.scope !== 'provider');
}

async function checkAlphaVantage({ config, fetchImpl, now, cache, budget, symbol, secrets }) {
  const t = new Tracker('alpha_vantage');
  const out = {
    id: ALPHA_VANTAGE.id, name: ALPHA_VANTAGE.name, delayLabel: ALPHA_VANTAGE.delayLabel,
    target: symbol, status: 'failed', requests: 0, steps: [], sample: null, error: null, assumptions: t.list,
  };
  if (!config.alphaVantage.apiKey) {
    out.status = 'setup_required';
    out.error = errorInfo(errors.notConfigured(ALPHA_VANTAGE.name, ALPHA_VANTAGE.keyEnv), secrets);
    return out;
  }
  out.steps.push({ name: 'מפתח מוגדר (הערך לא מוצג)', ok: true });
  try {
    await consume(budget, ALPHA_VANTAGE);
    out.requests++;
    const series = await fetchDailySeries(config.alphaVantage, symbol, fetchImpl, { inspect: (r) => inspectAlphaVantage(r, t) });
    const q = quoteFromBars(series.bars);
    const last = series.bars.at(-1);
    const completed = lastCompletedSessionDate(now());
    t.set('av.eod', last.date <= completed || usMarketSession(now()).state !== 'open',
      `תאריך הנתון האחרון ${last.date}; יום המסחר האחרון שהסתיים ${completed}; Last Refreshed: ${series.lastRefreshed}`);
    out.steps.push({ name: 'התקבלו מחיר והיסטוריה', ok: true, detail: `${series.bars.length} ימי מסחר` });
    out.sample = {
      symbol: series.symbol, price: q.price, previousClose: q.previousClose, changePct: q.changePct,
      volume: q.volume, asOf: last.t, asOfLabel: `${last.date} סגירה (16:00 ניו יורק)`,
      lastRefreshed: series.lastRefreshed, historyPoints: series.bars.length,
      firstDate: series.bars[0].date, lastDate: last.date, droppedRows: series.dropped,
      old: isStockSeriesOld(last.date, now()),
    };
    cache?.set(`av:daily:${symbol}`, series);
    out.status = 'passed';
  } catch (err) {
    out.error = errorInfo(err, secrets);
    out.steps.push({ name: 'קבלת מחיר והיסטוריה', ok: false, detail: out.error.message });
  }
  if (out.status === 'passed' && out.assumptions.some((a) => a.result === 'contradicted')) out.status = 'failed';
  return out;
}

async function checkCoinGecko({ config, fetchImpl, now, cache, budget, asset, secrets }) {
  const t = new Tracker('coingecko');
  const out = {
    id: COINGECKO.id, name: COINGECKO.name, delayLabel: COINGECKO.delayLabel, attribution: COINGECKO.attribution,
    target: asset ? `${asset.symbol} (${asset.id})` : null, status: 'failed', requests: 0, steps: [], sample: null, error: null,
    assumptions: t.list,
  };
  if (!config.coinGecko.apiKey) {
    out.status = 'setup_required';
    out.error = errorInfo(errors.notConfigured(COINGECKO.name, COINGECKO.keyEnv), secrets);
    return out;
  }
  if (!asset) {
    out.error = { code: 'bad_symbol_format', message: 'לא הוגדר נכס קריפטו לבדיקה (MARKET_CRYPTO_ASSETS).' };
    return out;
  }
  out.steps.push({ name: 'מפתח מוגדר (הערך לא מוצג)', ok: true });
  try {
    await consume(budget, COINGECKO);
    out.requests++;
    const quotes = await fetchMarkets(config.coinGecko, [asset.id], fetchImpl, { inspect: (r) => inspectMarkets(r, t) });
    const q = quotes.get(asset.id);
    if (!q) throw errors.invalidSymbol(asset.id, COINGECKO.name);
    const ageMin = q.asOf ? (now() - q.asOf) / 60000 : null;
    t.set('cg.fresh', ageMin !== null && ageMin <= 30, ageMin === null ? 'אין last_updated' : `גיל הנתון: ${ageMin.toFixed(1)} דקות`);
    out.steps.push({ name: 'התקבל מחיר', ok: true });

    await consume(budget, COINGECKO);
    out.requests++;
    const chart = await fetchMarketChart(config.coinGecko, asset.id, 90, fetchImpl, { inspect: (r) => inspectChart(r, t) });
    out.steps.push({ name: 'התקבלה היסטוריה', ok: true, detail: `${chart.bars.length} נקודות` });
    out.sample = {
      symbol: asset.symbol, name: q.name, price: q.price, changePct: q.changePct, changeBasis: '24 שעות',
      volume24h: q.volume, asOf: q.asOf, ageMinutes: ageMin,
      historyPoints: chart.bars.length, firstPoint: chart.bars[0].t, lastPoint: chart.bars.at(-1).t,
      volumePoints: chart.bars.filter((b) => b.volume !== null).length, candles: false,
    };
    cache?.set(`cg:chart:${asset.id}:90`, chart);
    out.status = 'passed';
  } catch (err) {
    out.error = errorInfo(err, secrets);
    out.steps.push({ name: 'קבלת נתונים', ok: false, detail: out.error.message });
  }
  if (out.status === 'passed' && out.assumptions.some((a) => a.result === 'contradicted')) out.status = 'failed';
  return out;
}

export function overallStatus(providers) {
  const s = providers.map((p) => p.status);
  if (s.every((x) => x === 'passed')) return 'passed';
  if (s.some((x) => x === 'failed')) return 'failed';
  if (s.every((x) => x === 'setup_required')) return 'setup_required';
  return 'partial';
}

// Runs both provider checks. Requests are counted in the same quota store
// the app uses, and a successful result warms the app's cache.
export async function runConnectionCheck({
  config, fetchImpl = globalThis.fetch, now = () => Date.now(), cache = null, stock = null, crypto = null,
}) {
  const secrets = [config.alphaVantage.apiKey, config.coinGecko.apiKey];
  const store = cache ?? { meta: {}, persist() {}, set() {} };
  const avBudget = new RequestBudget({ name: 'alpha_vantage', perMinute: config.alphaVantage.perMinute, perDay: config.alphaVantage.perDay, cache: store, now });
  const cgBudget = new RequestBudget({ name: 'coingecko', perMinute: config.coinGecko.perMinute, perMonth: config.coinGecko.perMonth, cache: store, now });
  const stockSymbol = (stock ?? config.stocks[0]?.symbol ?? 'AAPL').toUpperCase();
  const cryptoAsset = crypto
    ? config.crypto.find((c) => c.symbol === crypto.toUpperCase()) ?? null
    : config.crypto[0] ?? null;

  const providers = [
    await checkAlphaVantage({ config, fetchImpl, now, cache, budget: avBudget, symbol: stockSymbol, secrets }),
    await checkCoinGecko({ config, fetchImpl, now, cache, budget: cgBudget, asset: cryptoAsset, secrets }),
  ];
  const report = { ranAt: now(), overall: overallStatus(providers), providers };
  // Final guard: nothing that looks like a key may leave this function.
  return JSON.parse(redact(JSON.stringify(report), secrets));
}
