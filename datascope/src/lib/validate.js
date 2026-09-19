/**
 * Import validation.
 *
 * The contract is strict on purpose: an import either produces a dataset the
 * rest of the app can trust completely, or it produces a report and no dataset.
 * Rows are never dropped quietly and a missing value is never replaced with a
 * guess - a silently repaired dataset is worse than a rejected one, because the
 * statistics downstream would look just as confident either way.
 */

import { parseCsv, CsvParseError } from './csv.js';

export const LIMITS = Object.freeze({
  MAX_BYTES: 5 * 1024 * 1024,
  MAX_ROWS: 50_000,
  MAX_SYMBOL_LENGTH: 64,
  MAX_ISSUES_REPORTED: 200,
  MAX_VALUE_PREVIEW: 40,
});

export const REQUIRED_COLUMNS = Object.freeze(['date', 'symbol', 'close', 'volume']);

const DATE_SHAPE = /^\d{4}-\d{2}-\d{2}$/;
// No thousands separators, no currency, no whitespace: anything ambiguous is a
// validation error the user can see and fix, not something we try to interpret.
const NUMBER_SHAPE = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/**
 * Strict YYYY-MM-DD calendar check. Uses UTC arithmetic only, so the result
 * never depends on the machine's timezone.
 * @param {string} value
 * @returns {boolean}
 */
export function isValidIsoDate(value) {
  if (!DATE_SHAPE.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const stamp = Date.UTC(year, month - 1, day);
  const date = new Date(stamp);
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

/**
 * @param {string} value
 * @returns {number|null} A finite number, or null when the text is not an
 *   unambiguous plain number (this includes overflow to Infinity).
 */
export function parseStrictNumber(value) {
  if (!NUMBER_SHAPE.test(value)) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function preview(value) {
  const text = String(value);
  return text.length > LIMITS.MAX_VALUE_PREVIEW
    ? `${text.slice(0, LIMITS.MAX_VALUE_PREVIEW)}…`
    : text;
}

/**
 * @typedef {object} Issue
 * @property {string} kind Machine-readable category.
 * @property {number|null} row 1-based line number in the source file.
 * @property {string|null} column Column name, when the issue is about one cell.
 * @property {string|null} value Raw text, truncated. Rendered as text, never HTML.
 * @property {string} message Hebrew, actionable.
 */

class IssueList {
  constructor() {
    /** @type {Issue[]} */
    this.items = [];
    this.total = 0;
  }

  add(kind, message, { row = null, column = null, value = null } = {}) {
    this.total += 1;
    if (this.items.length < LIMITS.MAX_ISSUES_REPORTED) {
      this.items.push({
        kind,
        row,
        column,
        value: value === null ? null : preview(value),
        message,
      });
    }
  }

  get any() {
    return this.total > 0;
  }
}

function failure(issues, warnings, meta) {
  return {
    ok: false,
    issues: issues.items,
    issueCount: issues.total,
    truncatedIssues: issues.total > issues.items.length,
    warnings,
    dataset: null,
    meta,
  };
}

/**
 * True when the row sequence is already non-decreasing by date.
 * Dates are compared as YYYY-MM-DD strings, where lexicographic order *is*
 * chronological order - no Date objects, so no timezone can shift a day.
 * @param {{date: string}[]} rows
 */
export function isChronological(rows) {
  for (let i = 1; i < rows.length; i += 1) {
    if (rows[i].date < rows[i - 1].date) return false;
  }
  return true;
}

/**
 * Sorts chronologically, breaking date ties by symbol so the order is total and
 * reproducible. Returns a new array plus whether sorting changed anything.
 * @template {{date: string, symbol: string}} T
 * @param {T[]} rows
 * @returns {{rows: T[], wasReordered: boolean}}
 */
export function sortChronologically(rows) {
  const wasReordered = !isChronological(rows);
  const sorted = rows.slice().sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    if (a.symbol !== b.symbol) return a.symbol < b.symbol ? -1 : 1;
    return 0;
  });
  return { rows: sorted, wasReordered };
}

/**
 * Validates CSV text and, only if everything passes, builds the dataset.
 *
 * @param {string} text Decoded file text (BOM tolerated).
 * @param {{fileName?: string, byteSize?: number}} [source]
 * @returns {{ok: boolean, issues: Issue[], issueCount: number,
 *   truncatedIssues: boolean, warnings: string[], dataset: object|null,
 *   meta: object}}
 */
export function validateDataset(text, source = {}) {
  const fileName = source.fileName ?? '';
  const byteSize =
    typeof source.byteSize === 'number'
      ? source.byteSize
      : new TextEncoder().encode(text ?? '').length;

  const issues = new IssueList();
  /** @type {string[]} */
  const warnings = [];
  const meta = { fileName, byteSize, dataRowCount: 0, blankLines: 0 };

  if (byteSize > LIMITS.MAX_BYTES) {
    issues.add(
      'file-size',
      `הקובץ גדול מהמותר: ${byteSize} בייטים לעומת מקסימום ${LIMITS.MAX_BYTES} (5 מ״ב). יש לפצל את הקובץ או לצמצם את טווח התאריכים.`,
    );
    return failure(issues, warnings, meta);
  }

  let parsed;
  try {
    parsed = parseCsv(text ?? '');
  } catch (error) {
    if (error instanceof CsvParseError) {
      issues.add('csv-syntax', error.message, { row: error.line });
      return failure(issues, warnings, meta);
    }
    throw error;
  }
  meta.blankLines = parsed.blankLines;

  if (parsed.records.length === 0) {
    issues.add('empty-file', 'הקובץ ריק. נדרשת שורת כותרות ולפחות שורת נתונים אחת.');
    return failure(issues, warnings, meta);
  }

  const headerRecord = parsed.records[0];
  const header = headerRecord.cells.map((cell) => cell.trim().toLowerCase());
  /** @type {Record<string, number>} */
  const columnIndex = {};
  for (const name of REQUIRED_COLUMNS) {
    const first = header.indexOf(name);
    if (first === -1) {
      issues.add('missing-column', `חסרה עמודת חובה "${name}" בשורת הכותרות.`, {
        row: headerRecord.line,
        column: name,
      });
      continue;
    }
    columnIndex[name] = first;
    if (header.indexOf(name, first + 1) !== -1) {
      warnings.push(`העמודה "${name}" מופיעה יותר מפעם אחת; נעשה שימוש בהופעה הראשונה.`);
    }
  }
  if (issues.any) {
    issues.add(
      'header-hint',
      `שורת הכותרות הנדרשת היא: ${REQUIRED_COLUMNS.join(',')}. עמודות נוספות מותרות ויתעלמו מהן.`,
      { row: headerRecord.line },
    );
    return failure(issues, warnings, meta);
  }

  const dataRecords = parsed.records.slice(1);
  meta.dataRowCount = dataRecords.length;

  if (dataRecords.length === 0) {
    issues.add('no-rows', 'לא נמצאו שורות נתונים מתחת לשורת הכותרות.', {
      row: headerRecord.line,
    });
    return failure(issues, warnings, meta);
  }
  if (dataRecords.length > LIMITS.MAX_ROWS) {
    issues.add(
      'row-limit',
      `מספר שורות הנתונים (${dataRecords.length}) עובר את המקסימום ${LIMITS.MAX_ROWS}. יש לפצל את הקובץ.`,
    );
    return failure(issues, warnings, meta);
  }

  const headerWidth = header.length;
  /** @type {{date: string, symbol: string, close: number, volume: number, sourceRow: number}[]} */
  const rows = [];
  /** @type {Map<string, number>} */
  const seen = new Map();

  for (const record of dataRecords) {
    const row = record.line;
    const cells = record.cells;

    if (cells.length !== headerWidth) {
      issues.add(
        'column-count',
        `מספר התאים בשורה (${cells.length}) אינו תואם למספר הכותרות (${headerWidth}).`,
        { row },
      );
      continue;
    }

    const raw = {};
    let missing = false;
    for (const name of REQUIRED_COLUMNS) {
      const cell = (cells[columnIndex[name]] ?? '').trim();
      raw[name] = cell;
      if (cell === '') {
        issues.add('missing-cell', `תא ריק בעמודת חובה "${name}".`, { row, column: name });
        missing = true;
      }
    }
    if (missing) continue;

    let rowValid = true;

    if (!isValidIsoDate(raw.date)) {
      issues.add(
        'invalid-date',
        'תאריך לא חוקי. נדרש תאריך קיים בתבנית YYYY-MM-DD (למשל 2024-03-07).',
        { row, column: 'date', value: raw.date },
      );
      rowValid = false;
    }

    if (raw.symbol.length > LIMITS.MAX_SYMBOL_LENGTH) {
      issues.add(
        'symbol-length',
        `הסמל ארוך מ־${LIMITS.MAX_SYMBOL_LENGTH} תווים.`,
        { row, column: 'symbol', value: raw.symbol },
      );
      rowValid = false;
    }

    const close = parseStrictNumber(raw.close);
    if (close === null || close <= 0) {
      issues.add(
        'invalid-close',
        'מחיר סגירה חייב להיות מספר סופי וחיובי, ללא פסיקים, רווחים או סימני מטבע.',
        { row, column: 'close', value: raw.close },
      );
      rowValid = false;
    }

    const volume = parseStrictNumber(raw.volume);
    if (volume === null || volume < 0) {
      issues.add(
        'invalid-volume',
        'מחזור חייב להיות מספר סופי שאינו שלילי, ללא פסיקים או רווחים.',
        { row, column: 'volume', value: raw.volume },
      );
      rowValid = false;
    }

    if (!rowValid) continue;

    const key = `${raw.symbol}\u0000${raw.date}`;
    const firstRow = seen.get(key);
    if (firstRow !== undefined) {
      issues.add(
        'duplicate',
        `כפילות: הצמד סמל+תאריך (${raw.symbol}, ${raw.date}) מופיע גם בשורה ${firstRow}. יש להשאיר תצפית אחת לכל סמל ותאריך.`,
        { row, column: 'symbol', value: `${raw.symbol} ${raw.date}` },
      );
      continue;
    }
    seen.set(key, row);

    rows.push({
      date: raw.date,
      symbol: raw.symbol,
      close: /** @type {number} */ (close),
      volume: /** @type {number} */ (volume),
      sourceRow: row,
    });
  }

  if (issues.any) return failure(issues, warnings, meta);

  const { rows: sorted, wasReordered } = sortChronologically(rows);
  const symbols = [...new Set(sorted.map((r) => r.symbol))].sort((a, b) =>
    a.localeCompare(b, 'en'),
  );

  return {
    ok: true,
    issues: [],
    issueCount: 0,
    truncatedIssues: false,
    warnings,
    dataset: {
      fileName,
      byteSize,
      rowCount: sorted.length,
      rows: sorted,
      symbols,
      firstDate: sorted[0].date,
      lastDate: sorted[sorted.length - 1].date,
      wasReordered,
    },
    meta,
  };
}
