import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import {
  DEMO_SYMBOLS,
  demoTradingDays,
  generateDemoCsv,
  generateDemoRows,
} from '../src/lib/demo.js';
import { validateDataset } from '../src/lib/validate.js';
import { computeStats } from '../src/lib/stats.js';
import { selectRows } from '../src/lib/selection.js';

/**
 * The demo data is a fixture the tests and the UI share, so its bytes are
 * pinned. If the generator changes on purpose, update this digest in the same
 * commit - that is the point of it being here.
 */
const EXPECTED_SHA256 = '6e5902b94743cc483f62d93ac75f91b94c3c5180430b79f94fe9af4b3d5e7b48';

test('the generator is deterministic across calls', () => {
  assert.equal(generateDemoCsv(), generateDemoCsv());
  assert.deepEqual(generateDemoRows(), generateDemoRows());
});

test('the generated CSV matches its pinned digest', () => {
  const digest = createHash('sha256').update(generateDemoCsv()).digest('hex');
  assert.equal(digest, EXPECTED_SHA256);
});

test('the demo CSV passes the very same validator a user file goes through', () => {
  const result = validateDataset(generateDemoCsv(), { fileName: 'demo.csv' });
  assert.equal(result.ok, true);
  assert.equal(result.issueCount, 0);
  assert.deepEqual(result.dataset.symbols, ['DEMO_A', 'DEMO_B', 'DEMO_C']);
  assert.deepEqual([...DEMO_SYMBOLS], ['DEMO_A', 'DEMO_B', 'DEMO_C']);
});

test('the demo is grouped by symbol, so importing it exercises the reorder notice', () => {
  const result = validateDataset(generateDemoCsv());
  assert.equal(result.dataset.wasReordered, true);
});

test('every symbol covers the same trading days', () => {
  const days = demoTradingDays();
  const result = validateDataset(generateDemoCsv());
  for (const symbol of DEMO_SYMBOLS) {
    const rows = selectRows(result.dataset.rows, { symbol });
    assert.equal(rows.length, days.length, symbol);
    assert.deepEqual(rows.map((row) => row.date), days, symbol);
  }
});

test('the demo calendar has gaps: no weekends and some closed weekdays', () => {
  const days = demoTradingDays();
  assert.ok(days.length > 200);
  for (const day of days) {
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    assert.ok(weekday !== 0 && weekday !== 6, day);
  }
  // A fixed holiday list means missing calendar days inside the range.
  assert.equal(days.includes('2024-07-04'), false);
  assert.equal(days.includes('2024-12-25'), false);
  assert.equal(days.includes('2024-07-03'), true);
  assert.equal(days.includes('2024-07-05'), true);
});

test('all demo values satisfy the import rules by construction', () => {
  for (const row of generateDemoRows()) {
    assert.match(row.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(row.close > 0 && Number.isFinite(row.close), String(row.close));
    assert.ok(row.volume >= 0 && Number.isInteger(row.volume), String(row.volume));
    // Two decimals at most, so the CSV text stays clean and exact.
    assert.equal(Math.round(row.close * 100) / 100, row.close);
  }
});

test('the three demo series trend differently, which is what makes them useful', () => {
  const result = validateDataset(generateDemoCsv());
  const changeFor = (symbol) =>
    computeStats(selectRows(result.dataset.rows, { symbol })).percentChange;

  const a = changeFor('DEMO_A');
  const b = changeFor('DEMO_B');
  const c = changeFor('DEMO_C');
  assert.ok(a > 5, `DEMO_A should rise, got ${a}`);
  assert.ok(b < -2, `DEMO_B should fall, got ${b}`);
  assert.ok(c > 0 && c < a, `DEMO_C should rise mildly, got ${c}`);
});

test('the demo stays well inside the import limits', () => {
  const csv = generateDemoCsv();
  const rowCount = csv.trim().split('\n').length - 1;
  assert.ok(rowCount < 50_000);
  assert.ok(Buffer.byteLength(csv) < 5 * 1024 * 1024);
  assert.equal(csv.startsWith('date,symbol,close,volume\n'), true);
});
