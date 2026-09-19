/**
 * Minimal RFC 4180-style CSV reader.
 *
 * Deliberately dependency-free and streaming-free: the import path is capped at
 * 5 MB (see validate.js), so a single pass over a string is both fast enough and
 * far easier to audit than a parser that tries to be clever.
 *
 * Every value comes back as a raw string. Nothing here coerces, trims or
 * interprets a cell - that is validate.js's job, and keeping the two apart is
 * what lets the validator report the untouched text the user actually typed.
 */

const BOM = '﻿';

export class CsvParseError extends Error {
  /**
   * @param {string} message Hebrew, user-facing.
   * @param {number} line 1-based line where the offending record starts.
   */
  constructor(message, line) {
    super(message);
    this.name = 'CsvParseError';
    this.line = line;
  }
}

/**
 * @typedef {object} CsvRecord
 * @property {number} line 1-based line number where the record starts. A quoted
 *   field may span lines, so this is not always the record's index.
 * @property {string[]} cells Raw, untrimmed field values.
 */

/**
 * @param {string} text Full file text, with or without a UTF-8 BOM.
 * @returns {{records: CsvRecord[], blankLines: number}} `records[0]` is the
 *   header record when the file has one. Blank lines are counted, not returned.
 */
export function parseCsv(text) {
  if (typeof text !== 'string') {
    throw new TypeError('parseCsv expects a string');
  }
  const src = text.startsWith(BOM) ? text.slice(1) : text;

  /** @type {CsvRecord[]} */
  const records = [];
  let blankLines = 0;

  let cells = [];
  let field = '';
  let quoted = false;
  let recordHadQuotes = false;
  let physicalLine = 1; // line currently being consumed
  let recordLine = 1; // line the in-progress record started on

  function endRecord() {
    cells.push(field);
    field = '';
    const isBlank = cells.length === 1 && cells[0] === '' && !recordHadQuotes;
    if (isBlank) {
      blankLines += 1;
    } else {
      records.push({ line: recordLine, cells });
    }
    cells = [];
    recordHadQuotes = false;
    recordLine = physicalLine;
  }

  let i = 0;
  const n = src.length;
  while (i < n) {
    const ch = src[i];

    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        quoted = false;
        i += 1;
        continue;
      }
      if (ch === '\n') physicalLine += 1;
      field += ch;
      i += 1;
      continue;
    }

    if (ch === '"' && field === '') {
      quoted = true;
      recordHadQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ',') {
      cells.push(field);
      field = '';
      i += 1;
      continue;
    }
    if (ch === '\r') {
      i += src[i + 1] === '\n' ? 2 : 1;
      physicalLine += 1;
      endRecord();
      continue;
    }
    if (ch === '\n') {
      i += 1;
      physicalLine += 1;
      endRecord();
      continue;
    }

    // A stray quote inside an unquoted field is kept verbatim rather than
    // treated as an error: it is the common "5" inch" case, and the validator
    // will reject the cell anyway if the column needs a number.
    field += ch;
    i += 1;
  }

  if (quoted) {
    throw new CsvParseError(
      'מרכאות שלא נסגרו בקובץ. יש לסגור כל מרכאה שנפתחה.',
      recordLine,
    );
  }
  if (field !== '' || cells.length > 0) endRecord();

  return { records, blankLines };
}

/**
 * Quotes a single value for CSV output. Export-side formula neutralisation lives
 * in exporters.js - this function only handles CSV syntax.
 * @param {string} value
 * @returns {string}
 */
export function quoteCsvCell(value) {
  const text = String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}
