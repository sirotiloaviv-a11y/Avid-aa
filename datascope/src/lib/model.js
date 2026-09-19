/**
 * The normalized market data model.
 *
 * Every provider - Binance, Finnhub, Yahoo, CoinGecko - speaks its own wire
 * format. Each one translates into the three shapes below and nothing else, so
 * the dashboard, the chart and the alert engine never learn which API a number
 * came from.
 *
 * Two rules the whole app depends on:
 *   1. A price is a number or it is absent. A provider that cannot supply a
 *      field leaves it null rather than guessing, and the UI shows "—".
 *   2. Every quote carries its own timestamp and a `delayed` flag, because
 *      "real time" means different things on a crypto stream and on a free
 *      stock feed, and a price whose age is unknown is not usable.
 */

/**
 * @typedef {'crypto'|'stock'} AssetClass
 */

/**
 * @typedef {object} Asset
 * @property {string} key Stable identity: `${provider}:${symbol}`.
 * @property {string} provider Provider id, e.g. 'binance'.
 * @property {string} symbol The symbol as the provider expects it, e.g. 'BTCUSDT'.
 * @property {string} displaySymbol Human form, e.g. 'BTC/USDT' or 'AAPL'.
 * @property {string|null} name Full asset name, e.g. 'Bitcoin' or 'Apple Inc.'.
 *   Null until a provider resolves it - never invented.
 * @property {AssetClass} assetClass
 * @property {string|null} currency Quote currency, e.g. 'USDT' or 'USD'.
 */

/**
 * @typedef {object} Quote
 * @property {string} key Asset key.
 * @property {number|null} price Last traded price.
 * @property {number|null} open Session / 24h open.
 * @property {number|null} prevClose Previous session close (stocks).
 * @property {number|null} dayHigh
 * @property {number|null} dayLow
 * @property {number|null} changeAbs
 * @property {number|null} changePct
 * @property {number|null} volume Base-asset volume over the session / 24h.
 * @property {number|null} quoteVolume Turnover in the quote currency.
 * @property {number} ts Event time, epoch ms.
 * @property {string} source Provider id that produced it.
 * @property {boolean} delayed True when the provider does not promise real time.
 */

/**
 * @typedef {object} Candle
 * @property {number} t Open time, epoch ms.
 * @property {number} open
 * @property {number} high
 * @property {number} low
 * @property {number} close
 * @property {number} volume
 */

/**
 * @typedef {object} Trade
 * @property {string} key
 * @property {number} price
 * @property {number} size
 * @property {number} ts
 */

/** Connection states a provider can report. */
export const CONNECTION = Object.freeze({
  IDLE: 'idle',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  OFFLINE: 'offline',
  ERROR: 'error',
});

/** Hebrew labels for the status pill. */
export const CONNECTION_LABELS = Object.freeze({
  [CONNECTION.IDLE]: 'לא מחובר',
  [CONNECTION.CONNECTING]: 'מתחבר…',
  [CONNECTION.CONNECTED]: 'מחובר',
  [CONNECTION.RECONNECTING]: 'מתחבר מחדש…',
  [CONNECTION.OFFLINE]: 'מנותק',
  [CONNECTION.ERROR]: 'שגיאה',
});

/**
 * Parses a number that arrived as a string (every Binance numeric field is a
 * string) without ever producing NaN downstream.
 * @param {unknown} value
 * @returns {number|null}
 */
export function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Builds an asset key. Keys are compared as strings everywhere, so this is the
 * single definition of identity.
 * @param {string} provider
 * @param {string} symbol
 */
export function assetKey(provider, symbol) {
  return `${provider}:${String(symbol).toUpperCase()}`;
}

/**
 * Percentage change, 100 × (last / base − 1). Returns null when the base cannot
 * support a ratio, rather than Infinity or NaN.
 * @param {number|null} base
 * @param {number|null} last
 * @returns {number|null}
 */
export function percentChange(base, last) {
  if (base === null || last === null) return null;
  if (!Number.isFinite(base) || !Number.isFinite(last) || base <= 0) return null;
  return 100 * (last / base - 1);
}

/**
 * Fills in change fields a provider did not send, from the ones it did.
 * Never overwrites a value the provider supplied.
 *
 * The base is the previous close where there is one, and only then the session
 * open. That is what "change today" means on an equity: a stock that closed at
 * 100 and opened at 104 is up 4%, not flat, and measuring from the open would
 * hide every overnight gap. Providers that compute the figure themselves - the
 * Binance ticker always does - are left alone.
 *
 * @param {Quote} quote
 * @returns {Quote}
 */
export function completeQuote(quote) {
  const base = quote.prevClose ?? quote.open ?? null;
  const changeAbs =
    quote.changeAbs ?? (quote.price !== null && base !== null ? quote.price - base : null);
  const changePct = quote.changePct ?? percentChange(base, quote.price);
  return { ...quote, changeAbs, changePct };
}
