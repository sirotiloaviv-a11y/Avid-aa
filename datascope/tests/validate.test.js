import test from 'node:test';
import assert from 'node:assert/strict';

import {
  LIMITS,
  isValidIsoDate,
  parseStrictNumber,
  sortChronologically,
  validateDataset,
} from '../src/lib/validate.js';

const HEADER = 'date,symbol,close,volume';

function csv(...rows) {
  return `${[HEADER, ...rows].join('\n')}\n`;
}

function kinds(result) {
  return result.issues.map((issue) => issue.kind);
}

/* ------------------------------------------------------------- valid import */

test('a valid file imports and reports its symbols and range', () => {
  const result = validateDataset(
    csv('2024-01-02,AAA,100,1000', '2024-01-03,AAA,110,2000', '2024-01-02,BBB,50,10'),
    { fileName: 'ok.csv' },
  );
  assert.equal(result.ok, true);
  assert.equal(result.issueCount, 0);
  assert.equal(result.dataset.rowCount, 3);
  assert.deepEqual(result.dataset.symbols, ['AAA', 'BBB']);
  assert.equal(result.dataset.firstDate, '2024-01-02');
  assert.equal(result.dataset.lastDate, '2024-01-03');
  assert.equal(result.dataset.fileName, 'ok.csv');
});

test('header matching ignores case, surrounding spaces and column order', () => {
  const result = validateDataset(
    ' Volume , CLOSE ,Symbol, Date \n1000,100,AAA,2024-01-02\n',
    { fileName: 'reordered.csv' },
  );
  assert.equal(result.ok, true);
  assert.deepEqual(result.dataset.rows[0], {
    date: '2024-01-02',
    symbol: 'AAA',
    close: 100,
    volume: 1000,
    sourceRow: 2,
  });
});

test('extra columns are allowed and ignored', () => {
  const result = validateDataset('date,symbol,close,volume,open,note\n2024-01-02,AAA,100,1000,99,x\n');
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rowCount, 1);
});

test('quoted fields and a BOM are accepted', () => {
  const result = validateDataset('﻿date,symbol,close,volume\n"2024-01-02","A,B","100.5","1000"\n');
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rows[0].symbol, 'A,B');
  assert.equal(result.dataset.rows[0].close, 100.5);
});

test('rows keep their source line number for error reporting', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100,1000', '2024-01-03,AAA,101,1000'));
  assert.deepEqual(
    result.dataset.rows.map((row) => row.sourceRow),
    [2, 3],
  );
});

/* ----------------------------------------------------------- missing header */

test('a missing required column blocks the import and names the column', () => {
  const result = validateDataset('date,symbol,close\n2024-01-02,AAA,100\n', { fileName: 'x.csv' });
  assert.equal(result.ok, false);
  assert.equal(result.dataset, null);
  assert.ok(kinds(result).includes('missing-column'));
  assert.ok(result.issues.some((issue) => issue.column === 'volume'));
  assert.ok(result.issues.some((issue) => issue.message.includes('volume')));
});

test('several missing columns are all reported at once', () => {
  const result = validateDataset('date,close\n2024-01-02,100\n');
  const missing = result.issues.filter((issue) => issue.kind === 'missing-column');
  assert.equal(missing.length, 2);
  assert.deepEqual(
    missing.map((issue) => issue.column).sort(),
    ['symbol', 'volume'],
  );
});

test('an empty file and a header-only file are both rejected', () => {
  assert.equal(validateDataset('').ok, false);
  assert.deepEqual(kinds(validateDataset('')), ['empty-file']);
  assert.deepEqual(kinds(validateDataset(`${HEADER}\n`)), ['no-rows']);
});

/* ------------------------------------------------------------ invalid cells */

test('invalid dates are rejected with their row number', () => {
  const result = validateDataset(
    csv(
      '2024-01-02,AAA,100,1',
      '02/01/2024,AAA,100,1',
      '2024-02-30,AAA,100,1',
      '2024-1-5,AAA,100,1',
      '2024-13-01,AAA,100,1',
    ),
  );
  assert.equal(result.ok, false);
  const dateIssues = result.issues.filter((issue) => issue.kind === 'invalid-date');
  assert.deepEqual(
    dateIssues.map((issue) => issue.row),
    [3, 4, 5, 6],
  );
  assert.ok(dateIssues[0].value.includes('02/01/2024'));
});

test('isValidIsoDate rejects impossible calendar days and accepts leap days', () => {
  assert.equal(isValidIsoDate('2024-02-29'), true); // 2024 is a leap year
  assert.equal(isValidIsoDate('2023-02-29'), false);
  assert.equal(isValidIsoDate('2024-00-10'), false);
  assert.equal(isValidIsoDate('2024-04-31'), false);
  assert.equal(isValidIsoDate('24-04-01'), false);
  assert.equal(isValidIsoDate('2024-04-01T00:00:00Z'), false);
});

test('non-numeric, negative, zero and non-finite values are rejected', () => {
  const result = validateDataset(
    csv(
      '2024-01-02,AAA,abc,1',
      '2024-01-03,AAA,0,1',
      '2024-01-04,AAA,-5,1',
      '2024-01-05,AAA,1 000,1',
      '2024-01-06,AAA,"1,000",1',
      '2024-01-07,AAA,1e400,1',
      '2024-01-08,AAA,NaN,1',
      '2024-01-09,AAA,$10,1',
      '2024-01-10,AAA,100,-1',
      '2024-01-11,AAA,100,1.5e1',
    ),
  );
  assert.equal(result.ok, false);
  assert.deepEqual(
    result.issues.filter((issue) => issue.kind === 'invalid-close').map((issue) => issue.row),
    [2, 3, 4, 5, 6, 7, 8, 9],
  );
  assert.deepEqual(
    result.issues.filter((issue) => issue.kind === 'invalid-volume').map((issue) => issue.row),
    [10],
  );
});

test('a volume of zero and exponent notation are valid', () => {
  const result = validateDataset(csv('2024-01-02,AAA,1.5e2,0'));
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rows[0].close, 150);
  assert.equal(result.dataset.rows[0].volume, 0);
});

test('large but finite values are accepted without rounding', () => {
  const result = validateDataset(csv('2024-01-02,AAA,1.7976931348623157e308,9007199254740991'));
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rows[0].close, 1.7976931348623157e308);
  assert.equal(result.dataset.rows[0].volume, 9007199254740991);
});

test('parseStrictNumber refuses anything ambiguous', () => {
  assert.equal(parseStrictNumber('10'), 10);
  assert.equal(parseStrictNumber('10.25'), 10.25);
  assert.equal(parseStrictNumber('.5'), 0.5);
  assert.equal(parseStrictNumber('-3'), -3);
  assert.equal(parseStrictNumber('1e3'), 1000);
  assert.equal(parseStrictNumber(''), null);
  assert.equal(parseStrictNumber(' 10'), null);
  assert.equal(parseStrictNumber('10,5'), null);
  assert.equal(parseStrictNumber('Infinity'), null);
  assert.equal(parseStrictNumber('0x10'), null);
  assert.equal(parseStrictNumber('1e999'), null);
});

test('empty required cells are reported per column', () => {
  const result = validateDataset(csv('2024-01-02,,100,1', '2024-01-03,AAA,,1', ',AAA,100,'));
  assert.equal(result.ok, false);
  const missing = result.issues.filter((issue) => issue.kind === 'missing-cell');
  assert.deepEqual(
    missing.map((issue) => `${issue.row}:${issue.column}`),
    ['2:symbol', '3:close', '4:date', '4:volume'],
  );
});

test('a row with the wrong number of cells is reported, not padded', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100', '2024-01-03,AAA,100,1,extra'));
  assert.equal(result.ok, false);
  assert.deepEqual(
    result.issues.filter((issue) => issue.kind === 'column-count').map((issue) => issue.row),
    [2, 3],
  );
});

/* --------------------------------------------------------------- duplicates */

test('a duplicate symbol/date pair blocks the import and names both rows', () => {
  const result = validateDataset(
    csv('2024-01-02,AAA,100,1', '2024-01-03,AAA,101,1', '2024-01-02,AAA,102,1'),
  );
  assert.equal(result.ok, false);
  const duplicate = result.issues.find((issue) => issue.kind === 'duplicate');
  assert.equal(duplicate.row, 4);
  assert.match(duplicate.message, /שורה 2/);
});

test('the same date for different symbols is not a duplicate', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100,1', '2024-01-02,BBB,100,1'));
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rowCount, 2);
});

/* ------------------------------------------------------------------- limits */

test('a file over 5 MB is rejected before parsing', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100,1'), {
    fileName: 'big.csv',
    byteSize: LIMITS.MAX_BYTES + 1,
  });
  assert.equal(result.ok, false);
  assert.deepEqual(kinds(result), ['file-size']);
  assert.equal(result.dataset, null);
});

test('a file of exactly 5 MB is accepted', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100,1'), {
    byteSize: LIMITS.MAX_BYTES,
  });
  assert.equal(result.ok, true);
});

test('more than 50,000 data rows is rejected; exactly 50,000 is accepted', () => {
  const row = (index) => {
    const day = String((index % 28) + 1).padStart(2, '0');
    const month = String((Math.floor(index / 28) % 12) + 1).padStart(2, '0');
    const year = 1900 + Math.floor(index / (28 * 12));
    return `${year}-${month}-${day},AAA,100,1`;
  };
  const atLimit = Array.from({ length: LIMITS.MAX_ROWS }, (_, i) => row(i));
  const overLimit = [...atLimit, row(LIMITS.MAX_ROWS)];

  const rejected = validateDataset(csv(...overLimit));
  assert.equal(rejected.ok, false);
  assert.deepEqual(kinds(rejected), ['row-limit']);

  const accepted = validateDataset(csv(...atLimit));
  assert.equal(accepted.ok, true);
  assert.equal(accepted.dataset.rowCount, LIMITS.MAX_ROWS);
});

test('the issue list is capped but the total count is not', () => {
  const rows = Array.from({ length: LIMITS.MAX_ISSUES_REPORTED + 25 }, (_, i) => `bad-date-${i},AAA,100,1`);
  const result = validateDataset(csv(...rows));
  assert.equal(result.ok, false);
  assert.equal(result.issues.length, LIMITS.MAX_ISSUES_REPORTED);
  assert.equal(result.issueCount, LIMITS.MAX_ISSUES_REPORTED + 25);
  assert.equal(result.truncatedIssues, true);
});

test('a symbol longer than the limit is rejected', () => {
  const result = validateDataset(csv(`2024-01-02,${'A'.repeat(LIMITS.MAX_SYMBOL_LENGTH + 1)},100,1`));
  assert.equal(result.ok, false);
  assert.deepEqual(kinds(result), ['symbol-length']);
});

/* -------------------------------------------------------------------- order */

test('out-of-order rows are sorted and the reordering is reported', () => {
  const result = validateDataset(
    csv('2024-03-01,AAA,103,1', '2024-01-02,AAA,100,1', '2024-02-01,AAA,101,1'),
  );
  assert.equal(result.ok, true);
  assert.equal(result.dataset.wasReordered, true);
  assert.deepEqual(
    result.dataset.rows.map((row) => row.date),
    ['2024-01-02', '2024-02-01', '2024-03-01'],
  );
});

test('an already chronological file is not reported as reordered', () => {
  const result = validateDataset(csv('2024-01-02,AAA,100,1', '2024-01-03,AAA,101,1'));
  assert.equal(result.dataset.wasReordered, false);
});

test('a file grouped by symbol is reordered chronologically across symbols', () => {
  const result = validateDataset(
    csv('2024-01-02,AAA,1,1', '2024-01-03,AAA,1,1', '2024-01-02,BBB,1,1', '2024-01-03,BBB,1,1'),
  );
  assert.equal(result.dataset.wasReordered, true);
  assert.deepEqual(
    result.dataset.rows.map((row) => `${row.date}/${row.symbol}`),
    ['2024-01-02/AAA', '2024-01-02/BBB', '2024-01-03/AAA', '2024-01-03/BBB'],
  );
});

test('sortChronologically does not mutate its input', () => {
  const rows = [
    { date: '2024-02-01', symbol: 'A' },
    { date: '2024-01-01', symbol: 'A' },
  ];
  const { rows: sorted, wasReordered } = sortChronologically(rows);
  assert.equal(wasReordered, true);
  assert.equal(rows[0].date, '2024-02-01');
  assert.equal(sorted[0].date, '2024-01-01');
});

test('gaps in the calendar are not errors', () => {
  const result = validateDataset(
    csv('2024-01-02,AAA,100,1', '2024-01-05,AAA,101,1', '2024-03-11,AAA,102,1'),
  );
  assert.equal(result.ok, true);
  assert.equal(result.issueCount, 0);
  assert.equal(result.dataset.rowCount, 3);
});

/* ------------------------------------------------------------------ nothing
   is silently discarded: a file with one bad row imports zero rows, not the
   good ones. */
test('one invalid row blocks the whole import', () => {
  const result = validateDataset(
    csv('2024-01-02,AAA,100,1', 'not-a-date,AAA,101,1', '2024-01-04,AAA,102,1'),
  );
  assert.equal(result.ok, false);
  assert.equal(result.dataset, null);
});

test('a duplicated header column is a warning, not a failure', () => {
  const result = validateDataset('date,symbol,close,volume,close\n2024-01-02,AAA,100,1,999\n');
  assert.equal(result.ok, true);
  assert.equal(result.dataset.rows[0].close, 100);
  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /close/);
});

test('an unterminated quote is reported as a CSV syntax issue', () => {
  const result = validateDataset(`${HEADER}\n2024-01-02,"AAA,100,1\n`);
  assert.equal(result.ok, false);
  assert.deepEqual(kinds(result), ['csv-syntax']);
  assert.equal(result.issues[0].row, 2);
});
