import test from 'node:test';
import assert from 'node:assert/strict';

import { computeStats, percentChange } from '../src/lib/stats.js';
import { formatPercent } from '../src/lib/format.js';
import { validateDataset } from '../src/lib/validate.js';
import { selectRows } from '../src/lib/selection.js';

function rows(...triples) {
  return triples.map(([date, close, volume]) => ({ date, symbol: 'AAA', close, volume }));
}

/**
 * The formula is evaluated exactly as specified - 100 × (last / first − 1) - with
 * no intermediate rounding, so a result carries ordinary binary floating-point
 * error (100 -> 110 computes as 10.000000000000009). These assertions therefore
 * check both halves of the contract: the computed value is the mathematical one
 * to well within display precision, and the displayed string is the expected one.
 */
function assertChange(actual, expectedNumber, expectedDisplay) {
  assert.ok(
    Math.abs(actual - expectedNumber) < 1e-9,
    `expected ~${expectedNumber}, got ${actual}`,
  );
  assert.equal(formatPercent(actual), expectedDisplay);
}

test('100 to 110 is a 10% change', () => {
  const stats = computeStats(rows(['2024-01-02', 100, 1], ['2024-01-03', 110, 1]));
  assertChange(stats.percentChange, 10, '+10.00%');
});

test('known percentage changes come out right', () => {
  assertChange(percentChange(100, 110), 10, '+10.00%');
  assertChange(percentChange(100, 90), -10, '−10.00%');
  assertChange(percentChange(100, 200), 100, '+100.00%');
  assertChange(percentChange(200, 100), -50, '−50.00%');
  assertChange(percentChange(50, 50), 0, '0.00%');
  assertChange(percentChange(4, 1), -75, '−75.00%');
  assertChange(percentChange(0.5, 0.75), 50, '+50.00%');
  // Exact in binary arithmetic, so these are strict.
  assert.equal(percentChange(100, 200), 100);
  assert.equal(percentChange(50, 50), 0);
  assert.equal(percentChange(4, 1), -75);
});

test('percentChange refuses an unusable base', () => {
  assert.equal(percentChange(0, 10), null);
  assert.equal(percentChange(-1, 10), null);
  assert.equal(percentChange(Number.NaN, 10), null);
});

test('intermediate values are not rounded; only display rounds', () => {
  // 100 -> 100.005 is 0.005%, a value any early rounding would flatten to zero.
  const stats = computeStats(rows(['2024-01-02', 100, 1], ['2024-01-03', 100.005, 1]));
  assert.ok(stats.percentChange > 0);
  assert.ok(Math.abs(stats.percentChange - 0.005) < 1e-12);
  // The raw value keeps the detail. The display rounds it away - to two decimals
  // this change reads as +0.00% - which is exactly why the rounding happens here
  // and not in the calculation.
  assert.equal(formatPercent(stats.percentChange), '+0.00%');
  assert.notEqual(stats.percentChange, 0);
});

test('an empty selection yields zeroed statistics and no dates', () => {
  const stats = computeStats([]);
  assert.equal(stats.count, 0);
  assert.equal(stats.firstDate, null);
  assert.equal(stats.lastDate, null);
  assert.equal(stats.percentChange, null);
  assert.equal(stats.minClose, null);
  assert.equal(stats.maxClose, null);
  assert.equal(stats.averageVolume, null);
  assert.equal(stats.totalVolume, 0);
});

test('a single observation gives a 0% change and equal first/last values', () => {
  const stats = computeStats(rows(['2024-05-06', 73.25, 4321]));
  assert.equal(stats.count, 1);
  assert.equal(stats.singleObservation, true);
  assert.equal(stats.firstDate, '2024-05-06');
  assert.equal(stats.lastDate, '2024-05-06');
  assert.equal(stats.firstClose, 73.25);
  assert.equal(stats.lastClose, 73.25);
  assert.equal(stats.percentChange, 0);
  assert.equal(stats.minClose, 73.25);
  assert.equal(stats.maxClose, 73.25);
  assert.equal(stats.averageVolume, 4321);
});

test('minimum and maximum carry the date they occurred on', () => {
  const stats = computeStats(
    rows(
      ['2024-01-02', 100, 10],
      ['2024-01-03', 80, 10],
      ['2024-01-04', 140, 10],
      ['2024-01-05', 120, 10],
    ),
  );
  assert.equal(stats.minClose, 80);
  assert.equal(stats.minCloseDate, '2024-01-03');
  assert.equal(stats.maxClose, 140);
  assert.equal(stats.maxCloseDate, '2024-01-04');
  assert.equal(stats.firstClose, 100);
  assert.equal(stats.lastClose, 120);
  assertChange(stats.percentChange, 20, '+20.00%');
});

test('the first of several equal extremes is the one reported', () => {
  const stats = computeStats(
    rows(['2024-01-02', 100, 1], ['2024-01-03', 50, 1], ['2024-01-04', 50, 1]),
  );
  assert.equal(stats.minCloseDate, '2024-01-03');
});

test('average volume is the arithmetic mean over observations present', () => {
  const stats = computeStats(
    rows(['2024-01-02', 10, 100], ['2024-01-03', 10, 200], ['2024-01-04', 10, 0]),
  );
  assert.equal(stats.totalVolume, 300);
  assert.equal(stats.averageVolume, 100);
});

test('out-of-order input is handled by importing it, which sorts it first', () => {
  const result = validateDataset(
    'date,symbol,close,volume\n2024-03-01,AAA,110,5\n2024-01-02,AAA,100,5\n2024-02-01,AAA,105,5\n',
  );
  assert.equal(result.ok, true);
  const stats = computeStats(selectRows(result.dataset.rows, { symbol: 'AAA' }));
  assert.equal(stats.firstDate, '2024-01-02');
  assert.equal(stats.firstClose, 100);
  assert.equal(stats.lastDate, '2024-03-01');
  assert.equal(stats.lastClose, 110);
  assertChange(stats.percentChange, 10, '+10.00%');
});

test('large but valid values do not overflow the statistics', () => {
  const stats = computeStats(
    rows(['2024-01-02', 1e10, 1e15], ['2024-01-03', 2e10, 1e15]),
  );
  assert.equal(stats.percentChange, 100);
  assert.equal(stats.averageVolume, 1e15);
  assert.ok(Number.isFinite(stats.totalVolume));
});

test('statistics never claim a cause for a movement', () => {
  const stats = computeStats(rows(['2024-01-02', 100, 1], ['2024-01-03', 150, 1]));
  assert.deepEqual(
    Object.keys(stats).filter((key) => /reason|cause|forecast|predict|signal/i.test(key)),
    [],
  );
});
