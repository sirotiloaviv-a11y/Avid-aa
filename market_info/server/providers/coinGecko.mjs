// CoinGecko (Demo plan): crypto prices and history. Its free data is served
// from a cache that refreshes every few minutes, so it is delayed, not live.
// The Demo plan terms require the "Powered by CoinGecko" attribution.
import { errors, fetchJson, retryAfterSeconds } from '../errors.mjs';

export const COINGECKO = {
  id: 'coingecko',
  name: 'CoinGecko',
  url: 'https://www.coingecko.com',
  covers: 'crypto',
  delay: 'delayed',
  delayLabel: 'מושהה — מתעדכן אצל הספק בדרך כלל כל כמה דקות, לא בזמן אמת',
  attribution: 'Powered by CoinGecko',
  keyEnv: 'COINGECKO_DEMO_API_KEY',
};

function checkStatus(res, what) {
  const name = COINGECKO.name;
  if (res.status >= 400 && res.body === null && res.status !== 429) throw errors.blocked(name, res.status);
  if (res.status === 429) throw errors.rateLimited(name, retryAfterSeconds(res.headers, 60));
  if (res.status === 401 || res.status === 403) throw errors.authFailed(name);
  if (res.status === 404) throw errors.invalidSymbol(what, name);
  if (res.status >= 400) throw errors.upstream(name, res.status);
  const code = res.body?.status?.error_code;
  if (code === 429) throw errors.rateLimited(name, 60);
  if (code) throw errors.badResponse(name, String(res.body.status.error_message ?? code).slice(0, 120));
}

const finite = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

// /coins/markets -> Map(id -> quote). Coins missing from the answer are
// simply absent; the caller reports them as unknown symbols.
export function mapMarkets(body) {
  if (!Array.isArray(body)) throw errors.badResponse(COINGECKO.name, 'ציפיתי לרשימה');
  const out = new Map();
  for (const c of body) {
    const price = finite(c?.current_price);
    if (!c?.id || price === null) continue;
    const change = finite(c.price_change_24h);
    const changePct = finite(c.price_change_percentage_24h);
    out.set(c.id, {
      id: c.id,
      ticker: String(c.symbol ?? '').toUpperCase(),
      name: c.name ?? c.id,
      price,
      change,
      changePct,
      previousClose: change !== null ? price - change : null,
      volume: finite(c.total_volume),
      asOf: c.last_updated ? Date.parse(c.last_updated) || null : null,
    });
  }
  return out;
}

// /coins/{id}/market_chart -> points. CoinGecko supplies price and rolling
// 24h volume samples, not candles, so open/high/low stay null.
export function mapMarketChart(body) {
  if (!body || !Array.isArray(body.prices)) throw errors.badResponse(COINGECKO.name, 'חסרה סדרת מחירים');
  const volumes = new Map((body.total_volumes ?? []).map(([t, v]) => [t, finite(v)]));
  const bars = body.prices
    .filter((p) => Array.isArray(p) && finite(p[0]) !== null && finite(p[1]) !== null && p[1] > 0)
    .map(([t, close]) => ({ t, open: null, high: null, low: null, close, volume: volumes.get(t) ?? null }))
    .sort((a, b) => a.t - b.t);
  const deduped = bars.filter((b, i) => i === 0 || b.t !== bars[i - 1].t);
  if (!deduped.length) throw errors.badResponse(COINGECKO.name, 'אין נקודות מחיר');
  return { bars: deduped, dropped: body.prices.length - deduped.length };
}

function headers(apiKey) {
  return { accept: 'application/json', 'x-cg-demo-api-key': apiKey };
}

export async function fetchMarkets({ apiKey, baseUrl, timeoutMs }, ids, fetchImpl, { inspect } = {}) {
  const url = new URL(`${baseUrl.replace(/\/$/, '')}/coins/markets`);
  url.search = new URLSearchParams({ vs_currency: 'usd', ids: ids.join(','), price_change_percentage: '24h' });
  const res = await fetchJson(fetchImpl, url, { headers: headers(apiKey), timeoutMs, provider: COINGECKO.name });
  inspect?.(res);
  checkStatus(res, ids.join(','));
  return mapMarkets(res.body);
}

export async function fetchMarketChart({ apiKey, baseUrl, timeoutMs }, id, days, fetchImpl, { inspect } = {}) {
  const url = new URL(`${baseUrl.replace(/\/$/, '')}/coins/${encodeURIComponent(id)}/market_chart`);
  url.search = new URLSearchParams({ vs_currency: 'usd', days: String(days), interval: 'daily' });
  const res = await fetchJson(fetchImpl, url, { headers: headers(apiKey), timeoutMs, provider: COINGECKO.name });
  inspect?.(res);
  checkStatus(res, id);
  return mapMarketChart(res.body);
}
