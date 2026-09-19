/**
 * Exports: filtered CSV and a Hebrew text report.
 *
 * Two safety rules are enforced here rather than at the call site:
 *
 * 1. Formula neutralisation. A spreadsheet treats a cell that starts with
 *    = + - @ (or a tab / carriage return) as a formula, which turns an innocent
 *    looking symbol name in an imported file into code that runs on whoever
 *    opens our export. Such cells get a leading apostrophe, which spreadsheets
 *    read as "this is text".
 * 2. Filename safety. The symbol comes from the imported file, so it is
 *    untrusted: it is reduced to a conservative character set and length before
 *    it can reach a download name.
 */

import { quoteCsvCell } from './csv.js';
import {
  formatDate,
  formatPercent,
  formatPrice,
  formatVolume,
  formatInteger,
} from './format.js';

export const EXPORT_COLUMNS = Object.freeze(['date', 'symbol', 'close', 'volume']);

const RISKY_FIRST_CHAR = /^[=+\-@\t\r]/;

/**
 * Neutralises spreadsheet formula injection for one cell value.
 * Applied to every exported cell, including numbers - our numeric exports are
 * non-negative, so nothing legitimate starts with one of these characters.
 * @param {string|number} value
 * @returns {string}
 */
export function neutralizeFormula(value) {
  const text = String(value ?? '');
  return RISKY_FIRST_CHAR.test(text) ? `'${text}` : text;
}

/**
 * One CSV cell: neutralised, then quoted if CSV syntax needs it.
 * @param {string|number} value
 */
export function exportCell(value) {
  return quoteCsvCell(neutralizeFormula(value));
}

/**
 * @param {{date: string, symbol: string, close: number, volume: number}[]} rows
 * @returns {string} CSV text with CRLF line endings and a trailing newline.
 */
export function buildCsv(rows) {
  const lines = [EXPORT_COLUMNS.join(',')];
  for (const row of rows) {
    lines.push(
      [
        exportCell(row.date),
        exportCell(row.symbol),
        exportCell(numberToPlainText(row.close)),
        exportCell(numberToPlainText(row.volume)),
      ].join(','),
    );
  }
  return `${lines.join('\r\n')}\r\n`;
}

/**
 * Plain decimal notation wherever a double can be written that way - a
 * spreadsheet reading "1e-7" back is a needless round trip through a format not
 * every tool parses. Values too extreme for plain notation (below 1e-100) keep
 * their exponential form: an unreadable-but-exact number beats a rounded one.
 * @param {number} value
 */
export function numberToPlainText(value) {
  if (!Number.isFinite(value)) return '';
  const text = String(value);
  if (!text.includes('e') && !text.includes('E')) return text;
  if (Number.isInteger(value)) return BigInt(value).toString();
  const expanded = value.toFixed(100).replace(/0+$/, '').replace(/\.$/, '');
  return Number(expanded) === value ? expanded : text;
}

/**
 * Builds a download filename: datascope_<symbol>_<date>.<ext>
 * The symbol is untrusted input, so it is reduced to [A-Za-z0-9._-], length
 * capped, and never allowed to become empty, "." or "..".
 * @param {string} symbol
 * @param {string} dateIso YYYY-MM-DD
 * @param {string} extension Without the dot.
 */
export function safeFileName(symbol, dateIso, extension) {
  let name = String(symbol ?? '')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^[._-]+/, '')
    .replace(/[._-]+$/, '')
    .slice(0, 40)
    .replace(/[._-]+$/, '');
  if (name === '' || name === '.' || name === '..') name = 'symbol';
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(dateIso)) ? dateIso : 'unknown-date';
  const ext = String(extension).replace(/[^A-Za-z0-9]/g, '') || 'txt';
  return `datascope_${name}_${date}.${ext}`;
}

/**
 * The Hebrew text report: what was selected, what was computed, and what the
 * numbers do not say.
 *
 * @param {object} input
 * @param {string} input.symbol
 * @param {string} input.fileName
 * @param {boolean} input.isDemo
 * @param {{from: string|null, to: string|null}} input.requestedRange
 * @param {ReturnType<import('./stats.js').computeStats>} input.stats
 * @param {{title: string, paragraphs: string[], limitations: string[]}} input.summary
 * @param {string} input.generatedAt YYYY-MM-DD
 * @returns {string}
 */
export function buildTextReport({
  symbol,
  fileName,
  isDemo,
  requestedRange,
  stats,
  summary,
  generatedAt,
}) {
  const lines = [];
  const rule = '='.repeat(60);

  lines.push('DataScope — כלי לימודי לניתוח נתונים היסטוריים');
  lines.push(rule);
  lines.push(`תאריך הפקת הדוח: ${formatDate(generatedAt)}`);
  lines.push(`קובץ המקור: ${fileName || 'לא צוין'}`);
  if (isDemo) lines.push('סוג הנתונים: נתוני הדגמה מומצאים (לא נתוני שוק אמיתיים)');
  lines.push(`סמל נבחר: ${symbol || 'לא נבחר'}`);
  lines.push(
    `טווח שנבחר: ${requestedRange?.from ? formatDate(requestedRange.from) : 'מתחילת הנתונים'} עד ${
      requestedRange?.to ? formatDate(requestedRange.to) : 'סוף הנתונים'
    }`,
  );
  lines.push('');

  lines.push('נתונים מחושבים');
  lines.push('-'.repeat(60));
  if (stats.count === 0) {
    lines.push('אין תצפיות בטווח שנבחר, ולכן לא חושבו נתונים.');
  } else {
    lines.push(`מספר תצפיות: ${formatInteger(stats.count)}`);
    lines.push(`תצפית ראשונה: ${formatDate(stats.firstDate)} במחיר ${formatPrice(stats.firstClose)}`);
    lines.push(`תצפית אחרונה: ${formatDate(stats.lastDate)} במחיר ${formatPrice(stats.lastClose)}`);
    lines.push(`שינוי באחוזים בתקופה: ${formatPercent(stats.percentChange)}`);
    lines.push(`סגירה נמוכה: ${formatPrice(stats.minClose)} (${formatDate(stats.minCloseDate)})`);
    lines.push(`סגירה גבוהה: ${formatPrice(stats.maxClose)} (${formatDate(stats.maxCloseDate)})`);
    lines.push(`מחזור ממוצע לתצפית: ${formatVolume(stats.averageVolume)}`);
    lines.push('');
    lines.push('נוסחת השינוי באחוזים: 100 × (סגירה אחרונה / סגירה ראשונה − 1)');
  }
  lines.push('');

  lines.push(summary.title);
  lines.push('-'.repeat(60));
  for (const paragraph of summary.paragraphs) lines.push(paragraph);
  lines.push('');
  lines.push('(הסיכום נוצר מקומית מתבניות טקסט בקוד הכלי. לא נעשה שימוש במודל בינה מלאכותית.)');
  lines.push('');

  lines.push('מגבלות הנתונים');
  lines.push('-'.repeat(60));
  summary.limitations.forEach((item, index) => {
    lines.push(`${index + 1}. ${item}`);
  });
  lines.push('');
  lines.push(rule);
  lines.push('הופק מקומית בדפדפן. תוכן הקובץ שנטען לא נשלח לשום שרת.');

  return `${lines.join('\n')}\n`;
}
