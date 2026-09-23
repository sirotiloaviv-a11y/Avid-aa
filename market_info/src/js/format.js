import { priceDecimals } from './data/demoData.js';

export const TIME_ZONES = [
  { id: 'Asia/Jerusalem', label: 'ישראל (ירושלים)' },
  { id: 'UTC', label: 'זמן אוניברסלי (UTC)' },
  { id: 'Europe/London', label: 'לונדון' },
  { id: 'America/New_York', label: 'ניו יורק' },
  { id: 'Asia/Tokyo', label: 'טוקיו' },
];

export function tzName(tz) {
  return TIME_ZONES.find((z) => z.id === tz)?.label ?? tz;
}

export function tzOffset(tz, at = Date.now()) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'longOffset' })
    .formatToParts(new Date(at));
  const raw = parts.find((p) => p.type === 'timeZoneName')?.value ?? 'GMT';
  return raw === 'GMT' ? 'UTC+00:00' : raw.replace('GMT', 'UTC');
}

export function tzLabel(tz, at = Date.now()) {
  return `${tzName(tz)} · ${tzOffset(tz, at)}`;
}

export function formatPrice(value, currency = 'USD') {
  const d = priceDecimals(Math.abs(value));
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency, minimumFractionDigits: d, maximumFractionDigits: d,
  }).format(value);
}

export function formatSignedPrice(value, currency = 'USD') {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return sign + formatPrice(Math.abs(value), currency);
}

export function formatPct(value) {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

export function formatCompact(value) {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(value);
}

export function formatNumber(value) {
  return new Intl.NumberFormat('en-US').format(value);
}

export function formatMultiple(value) {
  return value.toFixed(1);
}

export function formatDateTime(ms, tz) {
  return new Intl.DateTimeFormat('he-IL', {
    timeZone: tz, day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(ms));
}

export function formatTime(ms, tz) {
  return new Intl.DateTimeFormat('he-IL', { timeZone: tz, hour: '2-digit', minute: '2-digit' }).format(new Date(ms));
}

export function formatShortDate(ms, tz) {
  return new Intl.DateTimeFormat('he-IL', { timeZone: tz, day: 'numeric', month: 'numeric' }).format(new Date(ms));
}

export function formatRelative(ms, now = Date.now()) {
  const rtf = new Intl.RelativeTimeFormat('he', { numeric: 'auto' });
  const diffMin = Math.round((ms - now) / 60000);
  if (Math.abs(diffMin) < 60) return rtf.format(diffMin, 'minute');
  const diffH = Math.round(diffMin / 60);
  if (Math.abs(diffH) < 48) return rtf.format(diffH, 'hour');
  return rtf.format(Math.round(diffH / 24), 'day');
}

// Calendar-day helpers work on "YYYY-MM-DD" keys in a given time zone.
export function dateKey(ms, tz) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(ms));
}

export function addDays(key, days) {
  const [y, m, d] = key.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

export function weekdayIndex(key) {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

// Weeks start on Sunday, as in the Israeli calendar.
export function weekKeys(key) {
  const start = addDays(key, -weekdayIndex(key));
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

export function isValidDateKey(key) {
  return /^\d{4}-\d{2}-\d{2}$/.test(key ?? '') && !Number.isNaN(Date.parse(key));
}

export function formatDayKey(key, { withWeekday = true } = {}) {
  const [y, m, d] = key.split('-').map(Number);
  return new Intl.DateTimeFormat('he-IL', {
    timeZone: 'UTC', weekday: withWeekday ? 'long' : undefined, day: 'numeric', month: 'long',
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatWeekdayShort(key) {
  const [y, m, d] = key.split('-').map(Number);
  return new Intl.DateTimeFormat('he-IL', { timeZone: 'UTC', weekday: 'short' })
    .format(new Date(Date.UTC(y, m - 1, d)));
}
