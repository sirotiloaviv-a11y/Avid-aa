// Normalized failure codes shared by the server and the browser.
export class MarketError extends Error {
  constructor(code, message, { status, retryAfterSec = null, provider = null } = {}) {
    super(message);
    this.code = code;
    this.status = status ?? STATUS[code] ?? 502;
    this.retryAfterSec = retryAfterSec;
    this.provider = provider;
  }

  toJSON() {
    return { code: this.code, message: this.message, retryAfterSec: this.retryAfterSec, provider: this.provider };
  }
}

const STATUS = {
  not_configured: 503,
  bad_symbol_format: 400,
  invalid_symbol: 404,
  rate_limited: 429,
  auth_failed: 502,
  premium_required: 502,
  upstream_unavailable: 502,
  network: 504,
  bad_response: 502,
};

export const errors = {
  notConfigured: (provider, envVar) => new MarketError('not_configured',
    `נדרשת הגדרה: לא הוגדר מפתח עבור ${provider} — המשתנה ${envVar} בקובץ ההגדרות המקומי. הוראות במסך ההגדרות.`, { provider }),
  badSymbolFormat: (symbol) => new MarketError('bad_symbol_format', `הסימול „${symbol}” אינו בפורמט תקין.`),
  invalidSymbol: (symbol, provider) => new MarketError('invalid_symbol',
    `הסימול ${symbol} לא נמצא אצל ${provider}.`, { provider }),
  rateLimited: (provider, retryAfterSec, local = false) => new MarketError('rate_limited',
    `${local ? 'הגעתם למכסת הבקשות שהוגדרה' : 'הספק הגביל את קצב הבקשות'} עבור ${provider}.` +
    (retryAfterSec ? ` אפשר לנסות שוב בעוד כ-${formatWait(retryAfterSec)}.` : ''),
    { retryAfterSec, provider }),
  authFailed: (provider) => new MarketError('auth_failed',
    `${provider} דחה את המפתח. בדקו את המפתח בקובץ ההגדרות המקומי.`, { provider }),
  premiumRequired: (provider) => new MarketError('premium_required',
    `הנתון המבוקש זמין אצל ${provider} רק במסלול בתשלום.`, { provider }),
  upstream: (provider, httpStatus) => new MarketError('upstream_unavailable',
    `${provider} אינו זמין כרגע${httpStatus ? ` (HTTP ${httpStatus})` : ''}.`, { provider }),
  // A non-JSON 4xx/5xx comes from something between us and the provider
  // (proxy, firewall, captive portal), not from the provider itself.
  blocked: (provider, httpStatus) => new MarketError('network',
    `הגישה ל-${provider} נחסמה בדרך (רשת, חומת אש או פרוקסי; HTTP ${httpStatus}). זו אינה תשובה של הספק.`, { provider }),
  network: (provider) => new MarketError('network',
    `אין חיבור ל-${provider}: ניתוק רשת, פסק זמן או חסימה.`, { provider }),
  badResponse: (provider, detail = '') => new MarketError('bad_response',
    `התקבלה תשובה לא צפויה מ-${provider}${detail ? `: ${detail}` : ''}.`, { provider }),
};

function formatWait(sec) {
  if (sec < 90) return `${Math.ceil(sec)} שניות`;
  if (sec < 5400) return `${Math.ceil(sec / 60)} דקות`;
  return `${Math.ceil(sec / 3600)} שעות`;
}

// Wraps fetch with a timeout and turns transport failures into MarketError.
export async function fetchJson(fetchImpl, url, { headers = {}, timeoutMs = 10000, provider }) {
  let res;
  try {
    res = await fetchImpl(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
  } catch {
    throw errors.network(provider);
  }
  let body = null;
  const text = await res.text().catch(() => '');
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  return { status: res.status, headers: res.headers, body, text };
}

export function retryAfterSeconds(headers, fallback) {
  const raw = headers?.get?.('retry-after');
  const n = Number(raw);
  if (raw && Number.isFinite(n) && n >= 0) return n;
  const date = raw ? Date.parse(raw) : NaN;
  if (Number.isFinite(date)) return Math.max(0, (date - Date.now()) / 1000);
  return fallback;
}
