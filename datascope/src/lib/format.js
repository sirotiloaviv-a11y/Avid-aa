/**
 * Display formatting. The only place in the app that rounds.
 *
 * Prices span eleven orders of magnitude here - BTC near 100,000 and meme coins
 * near 0.000008 - so a fixed two decimals is wrong in both directions: it hides
 * every digit that matters on the small one and adds noise to the large one.
 * `formatPrice` picks its precision from the magnitude instead.
 *
 * Numbers and times are rendered LTR inside the RTL page by the `.num` helper in
 * ui/dom.js, using an isolating element rather than bidi control characters, so
 * nothing invisible can leak into an export.
 */

const HE = 'he-IL';

/**
 * @param {number|null|undefined} value
 * @param {number} [minimumFractionDigits]
 * @param {number} [maximumFractionDigits]
 */
export function formatNumber(value, minimumFractionDigits = 0, maximumFractionDigits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(HE, { minimumFractionDigits, maximumFractionDigits }).format(value);
}

/**
 * Decimal places appropriate to a price's magnitude.
 * @param {number} value
 */
export function priceDigits(value) {
  const abs = Math.abs(value);
  if (abs === 0) return 2;
  if (abs >= 1000) return 2;
  if (abs >= 1) return 2;
  if (abs >= 0.01) return 4;
  if (abs >= 0.0001) return 6;
  return 8;
}

/**
 * A price, with no currency symbol attached: the quote currency is shown beside
 * the value in the UI, because the same number means different things on
 * BTC/USDT and on a euro-denominated listing.
 * @param {number|null} value
 */
export function formatPrice(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const digits = priceDigits(value);
  return formatNumber(value, digits, digits);
}

/** A signed price move, e.g. "+1.24". */
export function formatPriceDelta(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${formatPrice(Math.abs(value))}`;
}

/** @param {number|null} value */
export function formatInteger(value) {
  return formatNumber(value, 0, 0);
}

/**
 * Signed percentage, two decimals. The sign is explicit so a small fall cannot
 * be misread as a small rise at a glance.
 * @param {number|null} value
 */
export function formatPercent(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const body = new Intl.NumberFormat(HE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${body}%`;
}

/**
 * Compact magnitudes for axis ticks and volume: 1.2K / 3.4M / 5.6B.
 * @param {number|null} value
 */
export function formatCompact(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const units = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ];
  for (const [scale, suffix] of units) {
    if (abs >= scale) {
      const scaled = value / scale;
      return `${formatNumber(scaled, 0, Math.abs(scaled) < 10 ? 2 : 1)}${suffix}`;
    }
  }
  return formatNumber(value, 0, abs < 1 ? 4 : abs < 100 ? 2 : 0);
}

/**
 * A price for a chart axis: readable at a glance but never rounded into a lie.
 *
 * `formatCompact` is right for volume, where 108.3K is the useful reading, and
 * wrong for a price axis - a gridline labelled "64.2K" cannot be matched against
 * a quote of 64,185.36, which is exactly what someone reading a chart is doing.
 * Above 1,000 the decimals carry no information at gridline spacing, so they go;
 * below it they are the whole point, so they stay.
 *
 * @param {number|null} value
 */
export function formatAxisPrice(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1000) return formatNumber(value, 0, 0);
  if (abs >= 1) return formatNumber(value, 0, 2);
  return formatPrice(value);
}

/**
 * Wall-clock time in the viewer's own timezone, which is the only timezone that
 * answers "how long ago was this".
 * @param {number|null} ts Epoch ms.
 * @param {{seconds?: boolean}} [options]
 */
export function formatClock(ts, options = {}) {
  if (ts === null || ts === undefined || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(HE, {
    hour: '2-digit',
    minute: '2-digit',
    second: options.seconds === false ? undefined : '2-digit',
    hour12: false,
  }).format(new Date(ts));
}

/**
 * @param {number|null} ts Epoch ms.
 */
export function formatDateTime(ts) {
  if (ts === null || ts === undefined || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(HE, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(ts));
}

/** @param {number|null} ts Epoch ms. */
export function formatDate(ts) {
  if (ts === null || ts === undefined || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(HE, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(ts));
}

/**
 * Elapsed time in Hebrew: "עכשיו", "לפני 12 שניות", "לפני 4 דקות".
 * Used for the freshness indicator, so it stays coarse on purpose - a counter
 * ticking every second next to a price is noise, not information.
 * @param {number|null} ms
 */
export function formatAge(ms) {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 3) return 'עכשיו';
  if (seconds < 60) return `לפני ${seconds} שניות`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `לפני ${minutes} דקות`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `לפני ${hours} שעות`;
  const days = Math.round(hours / 24);
  return `לפני ${days} ימים`;
}

/**
 * A duration as a label: "5 דקות", "2 שעות".
 * @param {number} ms
 */
export function formatDuration(ms) {
  if (!Number.isFinite(ms)) return '—';
  const minutes = Math.round(ms / 60_000);
  if (minutes < 1) return 'פחות מדקה';
  if (minutes < 60) return `${minutes} דקות`;
  const hours = Math.round((minutes / 60) * 10) / 10;
  return `${hours} שעות`;
}

/** Today's date as YYYY-MM-DD in the viewer's own calendar day (export names). */
export function todayIso(now = new Date()) {
  const year = String(now.getFullYear()).padStart(4, '0');
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
