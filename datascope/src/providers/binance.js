/**
 * Binance connector - crypto, real time, no API key.
 *
 * Binance is the default crypto source because its market streams are public:
 * a browser can open the WebSocket directly, with no key and no backend, and
 * WebSocket connections are not subject to CORS. The REST endpoints used here
 * all send `Access-Control-Allow-Origin: *`.
 *
 * Every numeric field on the wire is a *string* ("0.0025"), which is why nothing
 * here touches a value without passing it through toNumber().
 *
 * The parse functions are exported separately from the connection code and are
 * pure: tests feed them recorded payloads, and the mock market server in
 * scripts/mock-market.mjs emits these same shapes.
 *
 * Wire formats handled (Binance spot market streams):
 *   <symbol>@ticker     - 24h rolling window statistics, ~1/second
 *   <symbol>@kline_1m   - 1 minute candles, updated live
 *   combined stream     - {"stream": "...", "data": {...}}
 */

import { assetKey, completeQuote, toNumber } from '../lib/model.js';

export const PROVIDER_ID = 'binance';

export const BINANCE_DEFAULTS = Object.freeze({
  rest: 'https://api.binance.com',
  ws: 'wss://stream.binance.com:9443',
});

/**
 * 'BTCUSDT' -> 'BTC/USDT'. Needs the quote asset, which exchangeInfo supplies;
 * without it the raw symbol is returned unchanged rather than split on a guess.
 * @param {string} symbol
 * @param {string|null} quoteAsset
 */
export function displaySymbolFor(symbol, quoteAsset) {
  if (!quoteAsset || !symbol.endsWith(quoteAsset)) return symbol;
  return `${symbol.slice(0, -quoteAsset.length)}/${quoteAsset}`;
}

/**
 * Parses a `<symbol>@ticker` payload into a Quote.
 *
 * @param {Record<string, unknown>} payload Raw `24hrTicker` event.
 * @returns {import('../lib/model.js').Quote|null} Null when the payload is not
 *   a ticker event, so a stray frame cannot become a fake price.
 */
export function parseTickerEvent(payload) {
  if (!payload || payload.e !== '24hrTicker' || typeof payload.s !== 'string') return null;
  return completeQuote({
    key: assetKey(PROVIDER_ID, payload.s),
    price: toNumber(payload.c),
    open: toNumber(payload.o),
    prevClose: toNumber(payload.x),
    dayHigh: toNumber(payload.h),
    dayLow: toNumber(payload.l),
    changeAbs: toNumber(payload.p),
    changePct: toNumber(payload.P),
    volume: toNumber(payload.v),
    quoteVolume: toNumber(payload.q),
    ts: toNumber(payload.E) ?? Date.now(),
    source: PROVIDER_ID,
    delayed: false,
  });
}

/**
 * Parses a `<symbol>@kline_1m` payload.
 * @param {Record<string, any>} payload
 * @returns {{key: string, candle: import('../lib/model.js').Candle, closed: boolean}|null}
 */
export function parseKlineEvent(payload) {
  if (!payload || payload.e !== 'kline' || !payload.k) return null;
  const k = payload.k;
  const open = toNumber(k.o);
  const high = toNumber(k.h);
  const low = toNumber(k.l);
  const close = toNumber(k.c);
  const volume = toNumber(k.v);
  const t = toNumber(k.t);
  if (t === null || close === null) return null;
  return {
    key: assetKey(PROVIDER_ID, payload.s),
    candle: { t, open: open ?? close, high: high ?? close, low: low ?? close, close, volume: volume ?? 0 },
    // `x` marks the candle as final; an open candle keeps being revised.
    closed: k.x === true,
  };
}

/**
 * Unwraps a combined-stream frame. A raw single-stream frame passes through.
 * @param {unknown} raw Parsed JSON from the socket.
 * @returns {Record<string, unknown>|null}
 */
export function unwrapStreamFrame(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const frame = /** @type {Record<string, unknown>} */ (raw);
  if (typeof frame.stream === 'string' && frame.data && typeof frame.data === 'object') {
    return /** @type {Record<string, unknown>} */ (frame.data);
  }
  return frame;
}

/**
 * Routes one socket frame to whichever parser matches it.
 * @param {string} text Raw socket message.
 * @returns {{kind: 'quote', quote: any}|{kind: 'candle', key: string, candle: any, closed: boolean}|null}
 */
export function parseSocketMessage(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  const data = unwrapStreamFrame(raw);
  if (!data) return null;

  const quote = parseTickerEvent(data);
  if (quote) return { kind: 'quote', quote };

  const kline = parseKlineEvent(data);
  if (kline) return { kind: 'candle', ...kline };

  return null;
}

/**
 * Parses `/api/v3/ticker/24hr` (one object, or the whole-market array).
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Quote[]}
 */
export function parseRestTickers(payload) {
  const rows = Array.isArray(payload) ? payload : [payload];
  const quotes = [];
  for (const row of rows) {
    if (!row || typeof row.symbol !== 'string') continue;
    const price = toNumber(row.lastPrice);
    if (price === null) continue;
    quotes.push(
      completeQuote({
        key: assetKey(PROVIDER_ID, row.symbol),
        price,
        open: toNumber(row.openPrice),
        prevClose: toNumber(row.prevClosePrice),
        dayHigh: toNumber(row.highPrice),
        dayLow: toNumber(row.lowPrice),
        changeAbs: toNumber(row.priceChange),
        changePct: toNumber(row.priceChangePercent),
        volume: toNumber(row.volume),
        quoteVolume: toNumber(row.quoteVolume),
        ts: toNumber(row.closeTime) ?? Date.now(),
        source: PROVIDER_ID,
        delayed: false,
      }),
    );
  }
  return quotes;
}

/**
 * Parses `/api/v3/klines`, which returns positional arrays:
 * [openTime, open, high, low, close, volume, closeTime, ...]
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Candle[]}
 */
export function parseRestKlines(payload) {
  if (!Array.isArray(payload)) return [];
  const candles = [];
  for (const row of payload) {
    if (!Array.isArray(row) || row.length < 6) continue;
    const t = toNumber(row[0]);
    const close = toNumber(row[4]);
    if (t === null || close === null) continue;
    candles.push({
      t,
      open: toNumber(row[1]) ?? close,
      high: toNumber(row[2]) ?? close,
      low: toNumber(row[3]) ?? close,
      close,
      volume: toNumber(row[5]) ?? 0,
    });
  }
  return candles;
}

/**
 * Parses `/api/v3/exchangeInfo` into tradable assets.
 *
 * Only symbols with status TRADING are kept: a delisted pair still appears in
 * exchangeInfo and would otherwise sit in the search results forever, silent.
 *
 * @param {unknown} payload
 * @param {{quoteAssets?: string[]}} [options] Restrict to these quote currencies.
 * @returns {import('../lib/model.js').Asset[]}
 */
export function parseExchangeInfo(payload, options = {}) {
  const quoteAssets = options.quoteAssets ? new Set(options.quoteAssets) : null;
  const symbols = payload && Array.isArray(payload.symbols) ? payload.symbols : [];
  const assets = [];
  for (const entry of symbols) {
    if (!entry || typeof entry.symbol !== 'string') continue;
    if (entry.status !== 'TRADING') continue;
    if (quoteAssets && !quoteAssets.has(entry.quoteAsset)) continue;
    assets.push({
      key: assetKey(PROVIDER_ID, entry.symbol),
      provider: PROVIDER_ID,
      symbol: entry.symbol,
      displaySymbol: displaySymbolFor(entry.symbol, entry.quoteAsset ?? null),
      // exchangeInfo carries ticker codes, not names. The name is resolved
      // separately (CoinGecko), and stays null until then.
      name: null,
      assetClass: 'crypto',
      currency: entry.quoteAsset ?? null,
      baseAsset: entry.baseAsset ?? null,
    });
  }
  return assets;
}

/**
 * Builds the combined-stream URL for a set of symbols.
 * @param {string[]} symbols e.g. ['BTCUSDT', 'ETHUSDT']
 * @param {{ws?: string, streams?: string[]}} [options]
 */
export function streamUrl(symbols, options = {}) {
  const base = options.ws ?? BINANCE_DEFAULTS.ws;
  const kinds = options.streams ?? ['ticker', 'kline_1m'];
  const streams = [];
  for (const symbol of symbols) {
    for (const kind of kinds) streams.push(`${symbol.toLowerCase()}@${kind}`);
  }
  return `${base}/stream?streams=${streams.join('/')}`;
}

/** REST helpers. Each returns a URL; fetching is the caller's job. */
export const endpoints = {
  /** @param {string} rest */
  exchangeInfo: (rest = BINANCE_DEFAULTS.rest) => `${rest}/api/v3/exchangeInfo`,
  /** @param {string[]} symbols */
  tickers: (symbols, rest = BINANCE_DEFAULTS.rest) =>
    symbols && symbols.length > 0
      ? `${rest}/api/v3/ticker/24hr?symbols=${encodeURIComponent(JSON.stringify(symbols))}`
      : `${rest}/api/v3/ticker/24hr`,
  /** @param {string} symbol */
  klines: (symbol, interval = '1m', limit = 240, rest = BINANCE_DEFAULTS.rest) =>
    `${rest}/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=${limit}`,
};
