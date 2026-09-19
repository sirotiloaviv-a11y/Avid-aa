/**
 * Exporting the alert history.
 *
 * The app imports no files - there is no CSV reader anywhere in it any more -
 * but the alert log is worth getting out of the browser, since it is the only
 * record that a rule fired while nobody was watching.
 *
 * Two safety rules are enforced here rather than at the call site:
 *
 * 1. Formula neutralisation. A spreadsheet treats a cell starting with = + - @
 *    (or a tab / carriage return) as a formula. Asset names and symbols in this
 *    log come from third-party APIs, so a cell could start with one of those
 *    characters and would then run as code in whoever opens the export. Such
 *    cells get a leading apostrophe, which spreadsheets read as "this is text".
 * 2. Filename safety. The symbol is likewise provider-controlled, so it is
 *    reduced to a conservative character set and length before it can reach a
 *    download name.
 */

import { formatDateTime } from './format.js';

export const HISTORY_COLUMNS = Object.freeze([
  'timestamp_iso',
  'time_local',
  'asset_name',
  'symbol',
  'alert_type',
  'rule',
  'price',
  'value',
  'message',
]);

const RISKY_FIRST_CHAR = /^[=+\-@\t\r]/;

/**
 * @param {string|number|null} value
 * @returns {string}
 */
export function neutralizeFormula(value) {
  const text = String(value ?? '');
  return RISKY_FIRST_CHAR.test(text) ? `'${text}` : text;
}

/**
 * Quotes a value for CSV output when the syntax requires it.
 * @param {string} value
 */
export function quoteCsvCell(value) {
  const text = String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

/** Neutralised, then quoted. */
export function exportCell(value) {
  return quoteCsvCell(neutralizeFormula(value));
}

/**
 * Full precision, plain decimal notation.
 * @param {number|null} value
 */
export function numberToPlainText(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '';
  const text = String(value);
  if (!text.includes('e') && !text.includes('E')) return text;
  if (Number.isInteger(value)) return BigInt(value).toString();
  const expanded = value.toFixed(100).replace(/0+$/, '').replace(/\.$/, '');
  return Number(expanded) === value ? expanded : text;
}

/**
 * @param {import('./alerts.js').AlertEvent[]} entries
 * @returns {string} CSV text with CRLF line endings.
 */
export function buildHistoryCsv(entries) {
  const lines = [HISTORY_COLUMNS.join(',')];
  for (const entry of entries) {
    lines.push(
      [
        exportCell(new Date(entry.ts).toISOString()),
        exportCell(formatDateTime(entry.ts)),
        exportCell(entry.name ?? ''),
        exportCell(entry.displaySymbol ?? entry.symbol ?? ''),
        exportCell(entry.type ?? ''),
        exportCell(entry.ruleLabel ?? ''),
        exportCell(numberToPlainText(entry.price)),
        exportCell(numberToPlainText(entry.value)),
        exportCell(entry.body ?? ''),
      ].join(','),
    );
  }
  return `${lines.join('\r\n')}\r\n`;
}

/**
 * Builds a download filename: datascope_<label>_<date>.<ext>
 * @param {string} label
 * @param {string} dateIso YYYY-MM-DD
 * @param {string} extension Without the dot.
 */
export function safeFileName(label, dateIso, extension) {
  let name = String(label ?? '')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^[._-]+/, '')
    .replace(/[._-]+$/, '')
    .slice(0, 40)
    .replace(/[._-]+$/, '');
  if (name === '' || name === '.' || name === '..') name = 'export';
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(dateIso)) ? dateIso : 'unknown-date';
  const ext = String(extension).replace(/[^A-Za-z0-9]/g, '') || 'txt';
  return `datascope_${name}_${date}.${ext}`;
}
