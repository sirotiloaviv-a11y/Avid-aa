import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildCsv,
  buildTextReport,
  exportCell,
  neutralizeFormula,
  numberToPlainText,
  safeFileName,
} from '../src/lib/exporters.js';
import { parseCsv } from '../src/lib/csv.js';
import { computeStats } from '../src/lib/stats.js';
import { buildSummary } from '../src/lib/summary.js';
import { validateDataset } from '../src/lib/validate.js';

/* ------------------------------------------------- formula injection guards */

test('cells that a spreadsheet would treat as a formula are neutralised', () => {
  assert.equal(neutralizeFormula('=1+1'), "'=1+1");
  assert.equal(neutralizeFormula('=HYPERLINK("http://x","click")'), '\'=HYPERLINK("http://x","click")');
  assert.equal(neutralizeFormula('+1'), "'+1");
  assert.equal(neutralizeFormula('-EVIL'), "'-EVIL");
  assert.equal(neutralizeFormula('@SUM(A1)'), "'@SUM(A1)");
  assert.equal(neutralizeFormula('\tTAB'), "'\tTAB");
  assert.equal(neutralizeFormula('\rCR'), "'\rCR");
});

test('ordinary values are left exactly as they are', () => {
  assert.equal(neutralizeFormula('AAA'), 'AAA');
  assert.equal(neutralizeFormula('100.5'), '100.5');
  assert.equal(neutralizeFormula('דמו'), 'דמו');
  assert.equal(neutralizeFormula('A=B'), 'A=B');
});

test('a dangerous symbol from an imported file is neutralised and quoted in the export', () => {
  const csv = buildCsv([
    { date: '2024-01-02', symbol: '=cmd|\' /C calc\'!A0', close: 100, volume: 5 },
  ]);
  const { records } = parseCsv(csv);
  assert.equal(records[1].cells[1].startsWith("'="), true);
  // Round-tripping keeps it inert: it is text, not a formula.
  assert.equal(records[1].cells[1], "'=cmd|' /C calc'!A0");
});

test('exportCell both neutralises and applies CSV quoting', () => {
  assert.equal(exportCell('=a,b'), '"\'=a,b"');
  assert.equal(exportCell('say "hi"'), '"say ""hi"""');
});

/* ------------------------------------------------------------- CSV building */

test('the exported CSV has the required header and one row per observation', () => {
  const rows = [
    { date: '2024-01-02', symbol: 'AAA', close: 100, volume: 1000 },
    { date: '2024-01-03', symbol: 'AAA', close: 100.25, volume: 0 },
  ];
  const csv = buildCsv(rows);
  assert.equal(csv.startsWith('date,symbol,close,volume\r\n'), true);
  assert.equal(csv.endsWith('\r\n'), true);
  const { records } = parseCsv(csv);
  assert.equal(records.length, 3);
  assert.deepEqual(records[2].cells, ['2024-01-03', 'AAA', '100.25', '0']);
});

test('an exported CSV can be imported back with identical values', () => {
  const source = validateDataset(
    'date,symbol,close,volume\n2024-01-02,AAA,100.5,1000\n2024-01-03,AAA,99.25,0\n',
  );
  const reimported = validateDataset(buildCsv(source.dataset.rows), { fileName: 'again.csv' });
  assert.equal(reimported.ok, true);
  assert.deepEqual(
    reimported.dataset.rows.map((row) => [row.date, row.symbol, row.close, row.volume]),
    source.dataset.rows.map((row) => [row.date, row.symbol, row.close, row.volume]),
  );
});

test('numbers are written in plain notation, never exponential', () => {
  assert.equal(numberToPlainText(1000), '1000');
  assert.equal(numberToPlainText(100.25), '100.25');
  assert.equal(numberToPlainText(0), '0');
  assert.equal(numberToPlainText(1e21).includes('e'), false);
  assert.equal(numberToPlainText(Number.POSITIVE_INFINITY), '');
});

/* ---------------------------------------------------------------- filenames */

test('the export filename contains the symbol and the export date', () => {
  assert.equal(safeFileName('DEMO_A', '2026-09-19', 'csv'), 'datascope_DEMO_A_2026-09-19.csv');
  assert.equal(safeFileName('DEMO_A', '2026-09-19', 'txt'), 'datascope_DEMO_A_2026-09-19.txt');
});

test('a hostile symbol cannot escape the filename', () => {
  const cases = [
    ['../../etc/passwd', 'datascope_etc_passwd_2026-09-19.csv'],
    ['a/b\\c', 'datascope_a_b_c_2026-09-19.csv'],
    ['..', 'datascope_symbol_2026-09-19.csv'],
    ['', 'datascope_symbol_2026-09-19.csv'],
    ['  ', 'datascope_symbol_2026-09-19.csv'],
    ['<script>', 'datascope_script_2026-09-19.csv'],
    ['שלום', 'datascope_symbol_2026-09-19.csv'],
  ];
  for (const [symbol, expected] of cases) {
    assert.equal(safeFileName(symbol, '2026-09-19', 'csv'), expected, symbol);
  }
});

test('filename parts are length-capped and the extension is sanitised', () => {
  const name = safeFileName('A'.repeat(80), '2026-09-19', 'c/sv');
  assert.equal(name, `datascope_${'A'.repeat(40)}_2026-09-19.csv`);
  assert.equal(safeFileName('AAA', 'not-a-date', 'csv'), 'datascope_AAA_unknown-date.csv');
});

/* ------------------------------------------------------------- text  report */

function reportFixture() {
  const result = validateDataset(
    'date,symbol,close,volume\n2024-01-02,AAA,100,1000\n2024-06-03,AAA,110,3000\n',
    { fileName: 'source.csv' },
  );
  const stats = computeStats(result.dataset.rows);
  const requestedRange = { from: '2024-01-01', to: '2024-12-31' };
  const summary = buildSummary({
    symbol: 'AAA',
    fileName: 'source.csv',
    isDemo: false,
    requestedRange,
    stats,
  });
  return buildTextReport({
    symbol: 'AAA',
    fileName: 'source.csv',
    isDemo: false,
    requestedRange,
    stats,
    summary,
    generatedAt: '2026-09-19',
  });
}

test('the Hebrew report states the period, the statistics and the limitations', () => {
  const report = reportFixture();
  assert.match(report, /DataScope/);
  assert.match(report, /כלי לימודי לניתוח נתונים היסטוריים/);
  assert.match(report, /סמל נבחר: AAA/);
  assert.match(report, /קובץ המקור: source\.csv/);
  assert.match(report, /תאריך הפקת הדוח: 19\.09\.2026/);
  assert.match(report, /מספר תצפיות: 2/);
  assert.match(report, /02\.01\.2024/);
  assert.match(report, /03\.06\.2024/);
  assert.match(report, /\+10\.00%/);
  assert.match(report, /סיכום אוטומטי/);
  assert.match(report, /מגבלות הנתונים/);
  assert.match(report, /פיצולי מניות ולדיבידנדים/);
  assert.match(report, /לא נעשה שימוש במודל בינה מלאכותית/);
  assert.match(report, /לא נשלח/);
});

test('the report never promises a recommendation or a forecast', () => {
  const report = reportFixture();
  for (const forbidden of ['המלצה', 'לקנות', 'למכור', 'תחזית', 'צפוי לעלות']) {
    assert.equal(report.includes(forbidden), false, forbidden);
  }
});

test('a report for an empty selection says so instead of inventing numbers', () => {
  const stats = computeStats([]);
  const requestedRange = { from: '2025-01-01', to: '2025-01-31' };
  const summary = buildSummary({
    symbol: 'AAA',
    fileName: 'source.csv',
    isDemo: false,
    requestedRange,
    stats,
  });
  const report = buildTextReport({
    symbol: 'AAA',
    fileName: 'source.csv',
    isDemo: false,
    requestedRange,
    stats,
    summary,
    generatedAt: '2026-09-19',
  });
  assert.match(report, /אין תצפיות בטווח שנבחר/);
  assert.equal(/מספר תצפיות:/.test(report), false);
});
