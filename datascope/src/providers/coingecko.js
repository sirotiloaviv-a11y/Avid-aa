/**
 * CoinGecko connector - crypto asset *names*, and a polled price fallback.
 *
 * Binance streams prices but knows only ticker codes: its exchangeInfo says
 * "BTC", never "Bitcoin". CoinGecko's public `/coins/list` is one CORS-enabled,
 * key-free request that maps codes to real names, which is what lets a
 * notification read "Bitcoin / BTCUSDT" instead of a bare symbol.
 *
 * It also serves as the crypto price fallback: Binance refuses connections from
 * some regions, and when that happens polling here keeps the dashboard working
 * rather than leaving it blank.
 *
 * Free tier is rate limited (roughly 5-15 calls/minute), so the poll interval is
 * deliberately slow and the name list is fetched once per session.
 */

import { assetKey, completeQuote, toNumber } from '../lib/model.js';

export const PROVIDER_ID = 'coingecko';

export const COINGECKO_DEFAULTS = Object.freeze({
  rest: 'https://api.coingecko.com/api/v3',
  /** Conservative: the free tier starts refusing well before this is a problem. */
  pollMs: 30_000,
});

/**
 * Parses `/coins/list`: [{"id":"bitcoin","symbol":"btc","name":"Bitcoin"}, ...]
 *
 * Several coins share a ticker code ("btc" is claimed by a dozen forks), so
 * ambiguous codes are resolved by market-cap rank when one is supplied; without
 * a rank the first entry wins and the rest are ignored. Names are only ever a
 * label here - no price decision depends on this mapping.
 *
 * @param {unknown} payload
 * @returns {Map<string, string>} upper-case ticker code -> name
 */
export function parseCoinList(payload) {
  const names = new Map();
  if (!Array.isArray(payload)) return names;
  for (const coin of payload) {
    if (!coin || typeof coin.symbol !== 'string' || typeof coin.name !== 'string') continue;
    const code = coin.symbol.toUpperCase();
    if (!names.has(code)) names.set(code, coin.name);
  }
  return names;
}

/**
 * Parses `/coins/markets`, used both for names and for fallback prices:
 * [{"id":"bitcoin","symbol":"btc","name":"Bitcoin","current_price":64000,
 *   "high_24h":..,"low_24h":..,"total_volume":..,
 *   "price_change_percentage_24h":..,"last_updated":"2024-..."}]
 *
 * @param {unknown} payload
 * @returns {{asset: import('../lib/model.js').Asset, quote: import('../lib/model.js').Quote}[]}
 */
export function parseMarkets(payload) {
  if (!Array.isArray(payload)) return [];
  const rows = [];
  for (const entry of payload) {
    if (!entry || typeof entry.id !== 'string') continue;
    const price = toNumber(entry.current_price);
    if (price === null) continue;

    const code = typeof entry.symbol === 'string' ? entry.symbol.toUpperCase() : entry.id.toUpperCase();
    const key = assetKey(PROVIDER_ID, entry.id);
    const changePct = toNumber(entry.price_change_percentage_24h);
    const ts = Date.parse(entry.last_updated ?? '');

    rows.push({
      asset: {
        key,
        provider: PROVIDER_ID,
        symbol: entry.id,
        displaySymbol: `${code}/USD`,
        name: typeof entry.name === 'string' ? entry.name : null,
        assetClass: 'crypto',
        currency: 'USD',
      },
      quote: completeQuote({
        key,
        price,
        open: null,
        prevClose: changePct !== null ? price / (1 + changePct / 100) : null,
        dayHigh: toNumber(entry.high_24h),
        dayLow: toNumber(entry.low_24h),
        changeAbs: toNumber(entry.price_change_24h),
        changePct,
        volume: null,
        quoteVolume: toNumber(entry.total_volume),
        ts: Number.isFinite(ts) ? ts : Date.now(),
        source: PROVIDER_ID,
        // CoinGecko aggregates across exchanges with its own cadence.
        delayed: true,
      }),
    });
  }
  return rows;
}

export const endpoints = {
  coinList: (rest = COINGECKO_DEFAULTS.rest) => `${rest}/coins/list`,
  /** @param {string[]} ids CoinGecko ids, e.g. ['bitcoin','ethereum'] */
  markets: (ids, rest = COINGECKO_DEFAULTS.rest) =>
    `${rest}/coins/markets?vs_currency=usd&ids=${encodeURIComponent(ids.join(','))}&order=market_cap_desc&sparkline=false`,
  topMarkets: (limit = 25, rest = COINGECKO_DEFAULTS.rest) =>
    `${rest}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=${limit}&page=1&sparkline=false`,
};
