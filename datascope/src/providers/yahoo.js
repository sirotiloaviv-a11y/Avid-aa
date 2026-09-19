/**
 * Yahoo Finance connector - US stocks, no signup, polled.
 *
 * Yahoo's endpoints do not send CORS headers, so a browser cannot call them
 * directly. The local server this app already runs exposes them under
 * `/api/yahoo/...` (see scripts/serve.mjs), which is why this provider needs no
 * API key: the proxy runs on the user's own machine and forwards nothing but the
 * symbol.
 *
 * This is the default stock source because it works the moment `npm start` does.
 * It is polled rather than streamed, and Yahoo makes no real-time guarantee, so
 * every quote it produces is flagged `delayed: true` and the UI says so. A
 * price of unknown age presented as live is worse than an honestly labelled one.
 *
 * Wire format handled - /v8/finance/chart/<symbol>?interval=1m&range=1d:
 *   {"chart":{"result":[{"meta":{...},"timestamp":[...],
 *     "indicators":{"quote":[{"open":[],"high":[],"low":[],"close":[],"volume":[]}]}}],
 *     "error":null}}
 */

import { assetKey, completeQuote, toNumber } from '../lib/model.js';

export const PROVIDER_ID = 'yahoo';

/** Served by the project's own local server; never a third-party proxy. */
export const YAHOO_DEFAULTS = Object.freeze({
  rest: '/api/yahoo',
});

/**
 * Pulls the price summary out of a chart response.
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Quote|null}
 */
export function parseChartQuote(payload) {
  const result = firstResult(payload);
  if (!result) return null;
  const meta = result.meta ?? {};
  const symbol = typeof meta.symbol === 'string' ? meta.symbol : null;
  if (!symbol) return null;

  const price = toNumber(meta.regularMarketPrice);
  if (price === null) return null;

  const prevClose = toNumber(meta.chartPreviousClose) ?? toNumber(meta.previousClose);
  const seconds = toNumber(meta.regularMarketTime);

  // Day high/low and volume are not always in meta; the candle series carries
  // them, so derive from there when they are missing rather than dropping them.
  const candles = parseChartCandles(payload);
  const derived = summariseCandles(candles);

  return completeQuote({
    key: assetKey(PROVIDER_ID, symbol),
    price,
    open: toNumber(meta.regularMarketDayOpen) ?? derived.open,
    prevClose,
    dayHigh: toNumber(meta.regularMarketDayHigh) ?? derived.high,
    dayLow: toNumber(meta.regularMarketDayLow) ?? derived.low,
    changeAbs: null,
    changePct: null,
    volume: toNumber(meta.regularMarketVolume) ?? derived.volume,
    quoteVolume: null,
    ts: seconds !== null ? seconds * 1000 : Date.now(),
    source: PROVIDER_ID,
    delayed: true,
  });
}

/**
 * Pulls the intraday candles out of a chart response.
 *
 * Yahoo pads its arrays with nulls for minutes that had no trade. Those entries
 * are dropped rather than carried forward: an invented flat candle would show up
 * in the chart and in a volume-surge rule as real activity.
 *
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Candle[]}
 */
export function parseChartCandles(payload) {
  const result = firstResult(payload);
  if (!result || !Array.isArray(result.timestamp)) return [];
  const quote = result.indicators?.quote?.[0];
  if (!quote) return [];

  const candles = [];
  for (let i = 0; i < result.timestamp.length; i += 1) {
    const t = toNumber(result.timestamp[i]);
    const close = toNumber(quote.close?.[i]);
    if (t === null || close === null) continue;
    candles.push({
      t: t * 1000,
      open: toNumber(quote.open?.[i]) ?? close,
      high: toNumber(quote.high?.[i]) ?? close,
      low: toNumber(quote.low?.[i]) ?? close,
      close,
      volume: toNumber(quote.volume?.[i]) ?? 0,
    });
  }
  return candles;
}

/**
 * The asset name, when the response carries one.
 * @param {unknown} payload
 * @returns {{symbol: string, name: string|null, currency: string|null}|null}
 */
export function parseChartAsset(payload) {
  const result = firstResult(payload);
  if (!result) return null;
  const meta = result.meta ?? {};
  if (typeof meta.symbol !== 'string') return null;
  const name =
    (typeof meta.longName === 'string' && meta.longName) ||
    (typeof meta.shortName === 'string' && meta.shortName) ||
    null;
  return {
    symbol: meta.symbol,
    name,
    currency: typeof meta.currency === 'string' ? meta.currency : null,
  };
}

/**
 * Yahoo reports failures inside a 200 response, under chart.error.
 * @param {unknown} payload
 * @returns {string|null} An error description, or null when the payload is fine.
 */
export function parseChartError(payload) {
  const error = payload?.chart?.error;
  if (!error) return null;
  if (typeof error === 'string') return error;
  const code = typeof error.code === 'string' ? error.code : 'error';
  const description = typeof error.description === 'string' ? error.description : '';
  return description ? `${code}: ${description}` : code;
}

function firstResult(payload) {
  const result = payload?.chart?.result;
  return Array.isArray(result) && result[0] ? result[0] : null;
}

function summariseCandles(candles) {
  if (candles.length === 0) return { open: null, high: null, low: null, volume: null };
  let high = candles[0].high;
  let low = candles[0].low;
  let volume = 0;
  for (const candle of candles) {
    if (candle.high > high) high = candle.high;
    if (candle.low < low) low = candle.low;
    volume += candle.volume;
  }
  return { open: candles[0].open, high, low, volume };
}

/**
 * Parses `/v1/finance/search?q=`:
 *   {"quotes":[{"symbol":"AAPL","shortname":"Apple Inc.","longname":"Apple Inc.",
 *     "quoteType":"EQUITY","exchange":"NMS"}]}
 *
 * Restricted to US equities and ETFs: the raw results mix in currencies, futures
 * and foreign listings that this dashboard's stock feed cannot quote.
 *
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Asset[]}
 */
export function parseSearch(payload) {
  const rows = payload && Array.isArray(payload.quotes) ? payload.quotes : [];
  const assets = [];
  for (const row of rows) {
    if (!row || typeof row.symbol !== 'string') continue;
    if (row.quoteType !== 'EQUITY' && row.quoteType !== 'ETF') continue;
    // A dot or dash suffix marks a foreign or class listing Yahoo quotes under
    // a different market; those are left out to keep the picker unambiguous.
    if (/[.\-=]/.test(row.symbol)) continue;
    const name =
      (typeof row.longname === 'string' && row.longname) ||
      (typeof row.shortname === 'string' && row.shortname) ||
      null;
    assets.push({
      key: assetKey(PROVIDER_ID, row.symbol),
      provider: PROVIDER_ID,
      symbol: row.symbol,
      displaySymbol: row.symbol,
      name,
      assetClass: 'stock',
      currency: 'USD',
    });
  }
  return assets;
}

export const endpoints = {
  /**
   * @param {string} query
   * @param {{rest?: string}} [options]
   */
  search: (query, options = {}) => {
    const rest = options.rest ?? YAHOO_DEFAULTS.rest;
    return `${rest}/v1/finance/search?q=${encodeURIComponent(query)}&quotesCount=12&newsCount=0`;
  },
  /**
   * @param {string} symbol
   * @param {{interval?: string, range?: string, rest?: string}} [options]
   */
  chart: (symbol, options = {}) => {
    const rest = options.rest ?? YAHOO_DEFAULTS.rest;
    const interval = options.interval ?? '1m';
    const range = options.range ?? '1d';
    return `${rest}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
  },
};
