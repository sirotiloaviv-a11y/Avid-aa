/**
 * Endpoint configuration.
 *
 * Endpoints are overridable from the query string, which is what lets the test
 * suite point the app at the local mock market server and lets a user switch to
 * binance.us when the global endpoint refuses their region.
 *
 * That override is restricted to an allowlist of hosts. Without it, a crafted
 * link - `?binanceWs=wss://attacker.example/…` - would repoint someone's
 * dashboard at a server that feeds it whatever prices it likes, and every alert
 * downstream would fire on fiction. The allowlist keeps the override useful for
 * the two cases that need it and worthless for that one.
 */

export const ALLOWED_HOSTS = Object.freeze([
  'api.binance.com',
  'stream.binance.com',
  'data-stream.binance.vision',
  'api.binance.us',
  'stream.binance.us',
  'api.coingecko.com',
  'finnhub.io',
  'ws.finnhub.io',
  'localhost',
  '127.0.0.1',
]);

export const DEFAULT_CONFIG = Object.freeze({
  binanceRest: 'https://api.binance.com',
  binanceWs: 'wss://stream.binance.com:9443',
  coingeckoRest: 'https://api.coingecko.com/api/v3',
  finnhubRest: 'https://finnhub.io/api/v1',
  finnhubWs: 'wss://ws.finnhub.io',
  /** Served by this project's own local server - see scripts/serve.mjs. */
  yahooRest: '/api/yahoo',
  /** How often the polled stock source refreshes. */
  stockPollMs: 15_000,
  /** How often the ticker bar refreshes its movers. */
  moversPollMs: 60_000,
});

/**
 * True when a URL may be used as an endpoint.
 *
 * Same-origin relative paths are always allowed: they can only reach the local
 * server the user started themselves.
 *
 * @param {string} value
 * @param {string[]} [allowedHosts]
 */
export function isAllowedEndpoint(value, allowedHosts = ALLOWED_HOSTS) {
  if (typeof value !== 'string' || value === '') return false;
  if (value.startsWith('/') && !value.startsWith('//')) return true;

  let url;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  if (!['https:', 'wss:', 'http:', 'ws:'].includes(url.protocol)) return false;

  // Plaintext is only acceptable for the local mock server; anything else must
  // be encrypted, or the prices arrive over a channel anyone on the path can
  // rewrite.
  const isLocal = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if ((url.protocol === 'http:' || url.protocol === 'ws:') && !isLocal) return false;

  return allowedHosts.includes(url.hostname);
}

/**
 * Reads overrides from a query string.
 * @param {string} search e.g. '?binanceWs=ws://127.0.0.1:4500/ws'
 * @param {{allowedHosts?: string[], base?: object}} [options]
 * @returns {{config: object, rejected: string[]}}
 */
export function configFromSearch(search, options = {}) {
  const base = { ...(options.base ?? DEFAULT_CONFIG) };
  const allowedHosts = options.allowedHosts ?? ALLOWED_HOSTS;
  /** @type {string[]} */
  const rejected = [];

  let params;
  try {
    params = new URLSearchParams(search ?? '');
  } catch {
    return { config: base, rejected };
  }

  const urlKeys = [
    'binanceRest',
    'binanceWs',
    'coingeckoRest',
    'finnhubRest',
    'finnhubWs',
    'yahooRest',
  ];
  for (const key of urlKeys) {
    const value = params.get(key);
    if (value === null) continue;
    if (isAllowedEndpoint(value, allowedHosts)) base[key] = value;
    else rejected.push(`${key}=${value}`);
  }

  const numberKeys = ['stockPollMs', 'moversPollMs'];
  for (const key of numberKeys) {
    const value = params.get(key);
    if (value === null) continue;
    const parsed = Number(value);
    // A floor of one second: a query parameter must not be able to turn the
    // dashboard into a request flood against a rate-limited free tier.
    if (Number.isFinite(parsed) && parsed >= 1000) base[key] = parsed;
    else rejected.push(`${key}=${value}`);
  }

  return { config: base, rejected };
}

/**
 * Which provider serves each asset class.
 * @param {{finnhubToken?: string|null}} options
 */
export function resolveProviders({ finnhubToken }) {
  return {
    crypto: 'binance',
    // Finnhub streams in real time but needs the user's own key; Yahoo through
    // the local proxy needs nothing, so it is the default.
    stock: finnhubToken ? 'finnhub' : 'yahoo',
  };
}
