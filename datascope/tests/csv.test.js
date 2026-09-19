import test from 'node:test';
import assert from 'node:assert/strict';

import { parseCsv, quoteCsvCell, CsvParseError } from '../src/lib/csv.js';

test('parses a plain file with a header and two rows', () => {
  const { records } = parseCsv('date,symbol,close,volume\n2024-01-02,AAA,10,5\n2024-01-03,AAA,11,6\n');
  assert.equal(records.length, 3);
  assert.deepEqual(records[0].cells, ['date', 'symbol', 'close', 'volume']);
  assert.deepEqual(records[1].cells, ['2024-01-02', 'AAA', '10', '5']);
  assert.equal(records[1].line, 2);
  assert.equal(records[2].line, 3);
});

test('strips a UTF-8 BOM from the first header cell', () => {
  const { records } = parseCsv('﻿date,symbol\n2024-01-02,AAA\n');
  assert.deepEqual(records[0].cells, ['date', 'symbol']);
});

test('handles CRLF line endings', () => {
  const { records } = parseCsv('a,b\r\n1,2\r\n');
  assert.equal(records.length, 2);
  assert.deepEqual(records[1].cells, ['1', '2']);
});

test('handles quoted fields containing commas, quotes and newlines', () => {
  const text = 'name,note\n"Smith, John","said ""hi"""\n"two\nlines",plain\n';
  const { records } = parseCsv(text);
  assert.deepEqual(records[1].cells, ['Smith, John', 'said "hi"']);
  assert.deepEqual(records[2].cells, ['two\nlines', 'plain']);
  // The record after a field that spanned two lines is still numbered correctly.
  assert.equal(records[2].line, 3);
});

test('keeps empty trailing cells', () => {
  const { records } = parseCsv('a,b,c\n1,,\n');
  assert.deepEqual(records[1].cells, ['1', '', '']);
});

test('counts blank lines instead of returning them as records', () => {
  const { records, blankLines } = parseCsv('a,b\n\n1,2\n\n');
  assert.equal(records.length, 2);
  assert.equal(blankLines, 2);
});

test('a file without a trailing newline still yields its last record', () => {
  const { records } = parseCsv('a,b\n1,2');
  assert.equal(records.length, 2);
  assert.deepEqual(records[1].cells, ['1', '2']);
});

test('an unterminated quote is a parse error naming the record line', () => {
  assert.throws(
    () => parseCsv('a,b\n1,"unterminated\n'),
    (error) => error instanceof CsvParseError && error.line === 2,
  );
});

test('quoteCsvCell quotes only what CSV syntax requires', () => {
  assert.equal(quoteCsvCell('plain'), 'plain');
  assert.equal(quoteCsvCell('with,comma'), '"with,comma"');
  assert.equal(quoteCsvCell('with"quote'), '"with""quote"');
  assert.equal(quoteCsvCell('with\nnewline'), '"with\nnewline"');
});

test('a value quoted on output parses back to the same value', () => {
  const original = 'Smith, "John"\nsecond line';
  const { records } = parseCsv(`value\n${quoteCsvCell(original)}\n`);
  assert.equal(records[1].cells[0], original);
});
