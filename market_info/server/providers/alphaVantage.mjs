// Alpha Vantage: US stocks, daily bars. The free tier gives end-of-day data
// and a small daily quota, so one TIME_SERIES_DAILY call serves both the
// latest close and the chart.
import { errors, fetchJson, retryAfterSeconds } from '../errors.mjs';
import { zonedTimeToUtc } from '../time.mjs';

export const ALPHA_VANTAGE = {
  id: 'alpha_vantage',
  name: 'Alpha Vantage',
  url: 'https://www.alphavantage.co',
  covers: 'stocks',
  delay: 'end_of_day',
  delayLabel: 'סוף יום — מחירי סגירה יומיים, לא בזמן אמת',
  keyEnv: 'ALPHA_VANTAGE_API_KEY',
};

const TZ_ALIASES = { 'US/Eastern': 'America/New_York' };

// Alpha Vantage reports quota and key problems with HTTP 200 and a text field.
export function classifyPayload(body, symbol) {
  const name = ALPHA_VANTAGE.name;
  if (!body || typeof body !== 'object') throw errors.badResponse(name, 'גוף התשובה ריק');
  if (body['Error Message']) throw errors.invalidSymbol(symbol, name);
  const text = String(body.Note ?? body.Information ?? '');
  if (text) {
    if (/api key|apikey/i.test(text) && /invalid|missing/i.test(text)) throw errors.authFailed(name);
    if (/premium/i.test(text) && !/rate limit|per day|frequency/i.test(text)) throw errors.premiumRequired(name);
    if (/rate limit|per day|per minute|frequency|requests/i.test(text)) {
      throw errors.rateLimited(name, /per day|daily/i.test(text) ? 3600 : 60);
    }
    throw errors.badResponse(name, text.slice(0, 120));
  }
}

// Maps TIME_SERIES_DAILY to ascending bars. Rows with an unusable close are
// dropped rather than repaired; a missing volume stays null.
export function mapDailySeries(body, symbol) {
  classifyPayload(body, symbol);
  const meta = body['Meta Data'];
  const series = body['Time Series (Daily)'];
  if (!meta || !series || typeof series !== 'object') throw errors.badResponse(ALPHA_VANTAGE.name, 'חסרה סדרת מחירים');
  const tz = TZ_ALIASES[meta['5. Time Zone']] ?? meta['5. Time Zone'] ?? 'America/New_York';
  let dropped = 0;
  const bars = [];
  for (const [date, row] of Object.entries(series)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { dropped++; continue; }
    const num = (k) => {
      const v = row?.[k];
      if (v === undefined || v === null || v === '') return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const close = num('4. close');
    if (close === null || close <= 0) { dropped++; continue; }
    const volume = num('5. volume');
    bars.push({
      date,
      t: zonedTimeToUtc(date, 16, 0, tz),
      open: num('1. open'),
      high: num('2. high'),
      low: num('3. low'),
      close,
      volume: volume !== null && volume >= 0 ? volume : null,
    });
  }
  bars.sort((a, b) => a.t - b.t);
  if (!bars.length) throw errors.badResponse(ALPHA_VANTAGE.name, 'אין נתוני מחיר בתשובה');
  return { symbol: meta['2. Symbol'] ?? symbol, lastRefreshed: meta['3. Last Refreshed'] ?? null, timeZone: tz, bars, dropped };
}

export async function fetchDailySeries({ apiKey, baseUrl, timeoutMs }, symbol, fetchImpl) {
  const url = new URL(baseUrl);
  url.search = new URLSearchParams({ function: 'TIME_SERIES_DAILY', symbol, outputsize: 'compact', apikey: apiKey });
  const res = await fetchJson(fetchImpl, url, { timeoutMs, provider: ALPHA_VANTAGE.name });
  if (res.status >= 400 && res.body === null && res.status !== 429) throw errors.blocked(ALPHA_VANTAGE.name, res.status);
  if (res.status === 429) throw errors.rateLimited(ALPHA_VANTAGE.name, retryAfterSeconds(res.headers, 60));
  if (res.status === 401 || res.status === 403) throw errors.authFailed(ALPHA_VANTAGE.name);
  if (res.status >= 400) throw errors.upstream(ALPHA_VANTAGE.name, res.status);
  return mapDailySeries(res.body, symbol);
}
