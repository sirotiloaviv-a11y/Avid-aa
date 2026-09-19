/**
 * Finnhub connector - US stocks, real time, free API key required.
 *
 * This is the only path that gives genuinely real-time US equity trades to a
 * browser with no backend: the socket is opened straight from the page with the
 * key as a query parameter, and `/quote` and `/search` are CORS-enabled.
 *
 * The key is the user's own free key. It is kept in this browser, sent only to
 * finnhub.io, and never to anywhere else - the audit script enforces that no
 * other host can be contacted at all.
 *
 * Wire formats handled:
 *   server -> {"type":"trade","data":[{"s":"AAPL","p":185.2,"t":1700000000000,"v":100}]}
 *   server -> {"type":"ping"}
 *   client -> {"type":"subscribe","symbol":"AAPL"}
 */

import { assetKey, completeQuote, toNumber } from '../lib/model.js';

export const PROVIDER_ID = 'finnhub';

export const FINNHUB_DEFAULTS = Object.freeze({
  rest: 'https://finnhub.io/api/v1',
  ws: 'wss://ws.finnhub.io',
});

/**
 * Parses a socket frame into trades.
 *
 * Finnhub batches trades per frame, and a single frame can carry several
 * symbols, so this returns an array rather than one trade.
 *
 * @param {string} text
 * @returns {{kind: 'trades', trades: import('../lib/model.js').Trade[]}
 *   |{kind: 'ping'}|{kind: 'error', message: string}|null}
 */
export function parseSocketMessage(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== 'object') return null;

  if (raw.type === 'ping') return { kind: 'ping' };
  if (raw.type === 'error') {
    return { kind: 'error', message: typeof raw.msg === 'string' ? raw.msg : 'שגיאה לא מזוהה' };
  }
  if (raw.type !== 'trade' || !Array.isArray(raw.data)) return null;

  const trades = [];
  for (const entry of raw.data) {
    if (!entry || typeof entry.s !== 'string') continue;
    const price = toNumber(entry.p);
    const ts = toNumber(entry.t);
    if (price === null || ts === null) continue;
    trades.push({
      key: assetKey(PROVIDER_ID, entry.s),
      price,
      size: toNumber(entry.v) ?? 0,
      ts,
    });
  }
  return trades.length > 0 ? { kind: 'trades', trades } : null;
}

/**
 * Parses `/quote`: {"c":261.74,"d":2.63,"dp":1.01,"h":263.31,"l":260.68,"o":261.07,"pc":259.11,"t":1582641000}
 *
 * Finnhub reports `t` in *seconds*; it becomes milliseconds here so the rest of
 * the app never has to ask which unit a timestamp is in. A quote of all zeros
 * is what Finnhub returns for an unknown symbol, and is rejected.
 *
 * @param {string} symbol
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Quote|null}
 */
export function parseQuote(symbol, payload) {
  if (!payload || typeof payload !== 'object') return null;
  const price = toNumber(payload.c);
  if (price === null || price === 0) return null;
  const seconds = toNumber(payload.t);
  return completeQuote({
    key: assetKey(PROVIDER_ID, symbol),
    price,
    open: toNumber(payload.o),
    prevClose: toNumber(payload.pc),
    dayHigh: toNumber(payload.h),
    dayLow: toNumber(payload.l),
    changeAbs: toNumber(payload.d),
    changePct: toNumber(payload.dp),
    volume: null, // /quote carries no volume on the free tier.
    quoteVolume: null,
    ts: seconds !== null ? seconds * 1000 : Date.now(),
    source: PROVIDER_ID,
    delayed: false,
  });
}

/**
 * Parses `/search?q=`: {"count":4,"result":[{"description":"APPLE INC","displaySymbol":"AAPL","symbol":"AAPL","type":"Common Stock"}]}
 *
 * Only plain equities on primary listings are kept: the raw results are full of
 * foreign cross-listings of the same company, which would make the dropdown
 * ambiguous.
 *
 * @param {unknown} payload
 * @returns {import('../lib/model.js').Asset[]}
 */
export function parseSearch(payload) {
  const rows = payload && Array.isArray(payload.result) ? payload.result : [];
  const assets = [];
  for (const row of rows) {
    if (!row || typeof row.symbol !== 'string') continue;
    // Cross-listings look like "AAPL.MX" / "APC.DE"; the primary US listing has
    // no dot suffix.
    if (row.symbol.includes('.')) continue;
    if (row.type && row.type !== 'Common Stock' && row.type !== 'ADR') continue;
    assets.push({
      key: assetKey(PROVIDER_ID, row.symbol),
      provider: PROVIDER_ID,
      symbol: row.symbol,
      displaySymbol: typeof row.displaySymbol === 'string' ? row.displaySymbol : row.symbol,
      name: typeof row.description === 'string' && row.description ? titleCase(row.description) : null,
      assetClass: 'stock',
      currency: 'USD',
    });
  }
  return assets;
}

/**
 * Parses `/stock/profile2`: {"name":"Apple Inc","ticker":"AAPL","currency":"USD",...}
 * @param {unknown} payload
 * @returns {{name: string|null, currency: string|null}}
 */
export function parseProfile(payload) {
  if (!payload || typeof payload !== 'object') return { name: null, currency: null };
  return {
    name: typeof payload.name === 'string' && payload.name ? payload.name : null,
    currency: typeof payload.currency === 'string' ? payload.currency : null,
  };
}

/**
 * Finnhub returns company names in capitals ("APPLE INC"). Presenting that as a
 * name shouts; this lower-cases it while leaving short all-caps tokens that are
 * probably initialisms alone.
 * @param {string} text
 */
export function titleCase(text) {
  return text
    .toLowerCase()
    .split(/\s+/)
    .map((word) => {
      if (word.length <= 1) return word.toUpperCase();
      return word[0].toUpperCase() + word.slice(1);
    })
    .join(' ');
}

/** @param {string} token */
export function socketUrl(token, ws = FINNHUB_DEFAULTS.ws) {
  return `${ws}?token=${encodeURIComponent(token)}`;
}

/** @param {string} symbol */
export function subscribeMessage(symbol) {
  return JSON.stringify({ type: 'subscribe', symbol });
}

/** @param {string} symbol */
export function unsubscribeMessage(symbol) {
  return JSON.stringify({ type: 'unsubscribe', symbol });
}

export const endpoints = {
  quote: (symbol, token, rest = FINNHUB_DEFAULTS.rest) =>
    `${rest}/quote?symbol=${encodeURIComponent(symbol)}&token=${encodeURIComponent(token)}`,
  search: (query, token, rest = FINNHUB_DEFAULTS.rest) =>
    `${rest}/search?q=${encodeURIComponent(query)}&token=${encodeURIComponent(token)}`,
  profile: (symbol, token, rest = FINNHUB_DEFAULTS.rest) =>
    `${rest}/stock/profile2?symbol=${encodeURIComponent(symbol)}&token=${encodeURIComponent(token)}`,
};
