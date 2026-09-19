/**
 * Display formatting. This is the only place rounding is allowed to happen.
 *
 * Dates are formatted from their YYYY-MM-DD text through UTC, so a date-only
 * record never shifts a day because of the viewer's timezone.
 *
 * Numbers and dates are rendered LTR inside the RTL page. The direction is set
 * by the DOM helpers (`num()` in ui/dom.js), not by embedding bidi control
 * characters in the strings - control characters would leak into exports.
 */

const HE = 'he-IL';

/**
 * @param {number|null} value
 * @param {number} [minimumFractionDigits]
 * @param {number} [maximumFractionDigits]
 */
export function formatNumber(value, minimumFractionDigits = 0, maximumFractionDigits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(HE, {
    minimumFractionDigits,
    maximumFractionDigits,
  }).format(value);
}

/**
 * Prices carry no currency: the file does not say what currency a symbol trades
 * in, and different symbols in one file may differ. Only digits are shown.
 * @param {number|null} value
 */
export function formatPrice(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const digits = Math.abs(value) > 0 && Math.abs(value) < 1 ? 4 : 2;
  return formatNumber(value, digits, digits);
}

/** @param {number|null} value */
export function formatInteger(value) {
  return formatNumber(value, 0, 0);
}

/** @param {number|null} value Average volume - kept to two decimals. */
export function formatVolume(value) {
  return formatNumber(value, 0, 2);
}

/**
 * Signed percentage, two decimals. The sign is explicit so a small negative
 * change cannot be mistaken for a small positive one.
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
 * Compact axis labels: 1.2K / 3.4M / 5.6B. Used only for chart ticks, where full
 * digits would collide; the table and the exports keep the exact values.
 * @param {number} value
 */
export function formatCompact(value) {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const units = [
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ];
  for (const [scale, suffix] of units) {
    if (abs >= scale) {
      const scaled = value / scale;
      const digits = Math.abs(scaled) < 10 ? 1 : 0;
      return `${formatNumber(scaled, 0, digits)}${suffix}`;
    }
  }
  return formatNumber(value, 0, abs < 10 ? 2 : 0);
}

/**
 * @param {string|null} iso YYYY-MM-DD
 * @returns {string} dd.MM.yyyy, or the raw text if it is not a date we parsed.
 */
export function formatDate(iso) {
  if (!iso || typeof iso !== 'string' || iso.length < 10) return '—';
  const year = iso.slice(0, 4);
  const month = iso.slice(5, 7);
  const day = iso.slice(8, 10);
  return `${day}.${month}.${year}`;
}

/** Short axis form: dd.MM (the year lives in the axis title). */
export function formatDateShort(iso) {
  if (!iso || typeof iso !== 'string' || iso.length < 10) return '';
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

/** Month + year, for a sparse time axis: MM.yyyy */
export function formatMonth(iso) {
  if (!iso || typeof iso !== 'string' || iso.length < 10) return '';
  return `${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
}

/**
 * Days between two ISO dates, computed in UTC.
 * @param {string} fromIso
 * @param {string} toIso
 */
export function daysBetween(fromIso, toIso) {
  return Math.round((isoToUtcMillis(toIso) - isoToUtcMillis(fromIso)) / 86_400_000);
}

/**
 * @param {string} iso YYYY-MM-DD
 * @returns {number} UTC milliseconds at midnight of that calendar day.
 */
export function isoToUtcMillis(iso) {
  return Date.UTC(
    Number(iso.slice(0, 4)),
    Number(iso.slice(5, 7)) - 1,
    Number(iso.slice(8, 10)),
  );
}

/** Today's date as YYYY-MM-DD, in the viewer's own calendar day. */
export function todayIso(now = new Date()) {
  const year = String(now.getFullYear()).padStart(4, '0');
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** @param {number} bytes */
export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${formatInteger(bytes)} בייט`;
  if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, 0, 1)} ק״ב`;
  return `${formatNumber(bytes / (1024 * 1024), 0, 2)} מ״ב`;
}
