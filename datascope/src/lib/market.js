/**
 * The in-memory market state: what each asset is, what it last traded at, and
 * its recent history.
 *
 * This is the single place the rest of the app reads from. Connectors write into
 * it, the dashboard and the chart read out of it, and the alert engine gets its
 * context from `contextFor()`. It holds no DOM and opens no socket, so the tests
 * can drive an entire session through it by hand.
 */

import { AssetRegistry } from './assets.js';
import { SeriesStore } from './series.js';
import { completeQuote } from './model.js';

export class MarketStore {
  /**
   * @param {{seriesOptions?: object}} [options]
   */
  constructor(options = {}) {
    this.registry = new AssetRegistry();
    this.series = new SeriesStore(options.seriesOptions);
    /** @type {Map<string, import('./model.js').Quote>} */
    this.quotes = new Map();
    /** @type {string[]} Keys, in the order the user sees them. */
    this.watchOrder = [];
  }

  /**
   * Adds an asset to the watchlist (idempotent).
   * @param {import('./model.js').Asset} asset
   */
  watch(asset) {
    const merged = this.registry.upsert(asset);
    if (!this.watchOrder.includes(merged.key)) this.watchOrder.push(merged.key);
    return merged;
  }

  /** @param {string} key */
  unwatch(key) {
    this.watchOrder = this.watchOrder.filter((entry) => entry !== key);
    this.quotes.delete(key);
    this.series.delete(key);
    this.registry.delete(key);
  }

  /**
   * Applies a quote. A quote older than the one already held is ignored, because
   * providers can deliver out of order after a reconnect and a price must never
   * go backwards in time.
   * @param {import('./model.js').Quote} quote
   * @returns {boolean} True when the store changed.
   */
  applyQuote(quote) {
    if (!quote || !quote.key) return false;
    const existing = this.quotes.get(quote.key);
    if (existing && quote.ts < existing.ts) return false;

    // Keep fields an earlier quote had that this one omits: Finnhub's trade
    // stream carries a price but no day open, and losing the open would blank
    // the day-change figure between polls.
    const merged = existing ? { ...existing, ...stripNulls(quote) } : quote;

    // The change figures are the exception. They describe a *particular* price,
    // so carrying them over from the previous quote would leave the card showing
    // a stale percentage beside a fresh price. Clear them unless this quote
    // supplied its own, and let completeQuote derive them again.
    if (existing) {
      if (quote.changeAbs === null || quote.changeAbs === undefined) merged.changeAbs = null;
      if (quote.changePct === null || quote.changePct === undefined) merged.changePct = null;
    }

    this.quotes.set(quote.key, completeQuote(merged));

    if (quote.price !== null && quote.price !== undefined) {
      const series = this.series.get(quote.key);
      series.lastPrice = quote.price;
      series.lastUpdateAt = quote.ts;
    }
    return true;
  }

  /**
   * @param {import('./model.js').Trade} trade
   */
  applyTrade(trade) {
    if (!trade || !trade.key) return false;
    this.series.get(trade.key).addTrade(trade.price, trade.size, trade.ts);

    const existing = this.quotes.get(trade.key);
    const next = completeQuote({
      key: trade.key,
      price: trade.price,
      open: existing?.open ?? null,
      prevClose: existing?.prevClose ?? null,
      dayHigh: existing?.dayHigh !== undefined && existing?.dayHigh !== null
        ? Math.max(existing.dayHigh, trade.price)
        : null,
      dayLow: existing?.dayLow !== undefined && existing?.dayLow !== null
        ? Math.min(existing.dayLow, trade.price)
        : null,
      changeAbs: null,
      changePct: null,
      volume: existing?.volume ?? null,
      quoteVolume: existing?.quoteVolume ?? null,
      ts: trade.ts,
      source: existing?.source ?? 'stream',
      delayed: existing?.delayed ?? false,
    });
    this.quotes.set(trade.key, next);
    return true;
  }

  /**
   * @param {string} key
   * @param {import('./model.js').Candle} candle
   */
  applyCandle(key, candle) {
    this.series.get(key).applyCandle(candle);
  }

  /**
   * @param {string} key
   * @param {import('./model.js').Candle[]} candles
   */
  seedSeries(key, candles) {
    this.series.get(key).seed(candles);
  }

  /** @param {string} key */
  quote(key) {
    return this.quotes.get(key) ?? null;
  }

  /**
   * The context the alert engine evaluates against.
   * @param {string} key
   */
  contextFor(key) {
    const asset = this.registry.get(key);
    if (!asset) return null;
    return {
      asset,
      quote: this.quotes.get(key) ?? null,
      series: this.series.peek(key),
    };
  }

  /** Watched assets, in display order. */
  watchlist() {
    return this.watchOrder
      .map((key) => this.registry.get(key))
      .filter((asset) => asset !== null);
  }

  /**
   * How stale the freshest data for an asset is.
   * @param {string} key
   * @param {number} now
   * @returns {number|null} Milliseconds, or null when nothing has arrived.
   */
  ageOf(key, now) {
    const quote = this.quotes.get(key);
    if (!quote) return null;
    return Math.max(0, now - quote.ts);
  }

  clear() {
    this.quotes.clear();
    this.series.clear();
    this.watchOrder = [];
  }
}

function stripNulls(object) {
  const out = {};
  for (const [key, value] of Object.entries(object)) {
    if (value !== null && value !== undefined) out[key] = value;
  }
  return out;
}

/**
 * The biggest movers among a set of quotes - what the ticker bar shows.
 *
 * Sorted by the size of the move regardless of direction, because a 6% fall is
 * exactly as newsworthy as a 6% rise. Assets with no change figure yet are left
 * out rather than sorted as zero.
 *
 * @param {{asset: import('./model.js').Asset, quote: import('./model.js').Quote}[]} rows
 * @param {{limit?: number}} [options]
 */
export function topMovers(rows, options = {}) {
  const limit = options.limit ?? 12;
  return rows
    .filter((row) => row.quote && typeof row.quote.changePct === 'number' && Number.isFinite(row.quote.changePct))
    .sort((a, b) => Math.abs(b.quote.changePct) - Math.abs(a.quote.changePct))
    .slice(0, limit);
}

/**
 * Intraday statistics for the selected asset, merging what the provider reported
 * with what the local series observed.
 *
 * Provider values win where they exist: an exchange's official session high is
 * authoritative, while the local series only knows what arrived since the page
 * was opened.
 *
 * @param {import('./model.js').Quote|null} quote
 * @param {import('./series.js').Series|null} series
 */
export function intradayStats(quote, series) {
  const summary = series ? series.summary() : { open: null, high: null, low: null, volume: 0, count: 0 };
  return {
    price: quote?.price ?? series?.lastPrice ?? null,
    open: quote?.open ?? summary.open,
    prevClose: quote?.prevClose ?? null,
    high: quote?.dayHigh ?? summary.high,
    low: quote?.dayLow ?? summary.low,
    changeAbs: quote?.changeAbs ?? null,
    changePct: quote?.changePct ?? null,
    volume: quote?.volume ?? (summary.volume || null),
    quoteVolume: quote?.quoteVolume ?? null,
    observedVolume: summary.volume,
    observedCount: summary.count,
    ts: quote?.ts ?? series?.lastUpdateAt ?? null,
    delayed: quote?.delayed ?? false,
    source: quote?.source ?? null,
  };
}
