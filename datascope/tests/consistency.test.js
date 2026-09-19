/**
 * Cross-module consistency: the statistics, the table, the summary and both
 * exports must all describe the same selection.
 *
 * The app derives every panel from one `selectRows()` call per render, so these
 * tests exercise that contract at the seam where a real inconsistency would
 * appear - the numbers a user compares between the stat cards, the table and the
 * downloaded file.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { validateDataset } from '../src/lib/validate.js';
import { computeStats } from '../src/lib/stats.js';
import { paginate, selectRows, sortRows, symbolBounds } from '../src/lib/selection.js';
import { buildCsv, buildTextReport } from '../src/lib/exporters.js';
import { buildSummary } from '../src/lib/summary.js';
import { formatDate, formatPercent, formatPrice } from '../src/lib/format.js';
import { parseCsv } from '../src/lib/csv.js';
import { generateDemoCsv } from '../src/lib/demo.js';

function demoDataset() {
  const result = validateDataset(generateDemoCsv(), { fileName: 'demo.csv' });
  assert.equal(result.ok, true);
  return result.dataset;
}

/** A spread of selections, including edge cases the UI can produce. */
const SELECTIONS = [
  { symbol: 'DEMO_A', from: null, to: null },
  { symbol: 'DEMO_A', from: '2024-03-01', to: '2024-06-30' },
  { symbol: 'DEMO_B', from: '2024-01-02', to: '2024-01-02' }, // single observation
  { symbol: 'DEMO_B', from: '2024-06-01', to: '2024-12-31' },
  { symbol: 'DEMO_C', from: '2024-12-25', to: '2024-12-25' }, // a closed day: empty
  { symbol: 'DEMO_C', from: null, to: '2024-02-15' },
];

test('statistics always describe exactly the filtered rows', () => {
  const dataset = demoDataset();
  for (const selection of SELECTIONS) {
    const rows = selectRows(dataset.rows, selection);
    const stats = computeStats(rows);
    const label = JSON.stringify(selection);

    assert.equal(stats.count, rows.length, label);
    if (rows.length === 0) {
      assert.equal(stats.firstDate, null, label);
      assert.equal(stats.percentChange, null, label);
      continue;
    }

    assert.equal(stats.firstDate, rows[0].date, label);
    assert.equal(stats.lastDate, rows[rows.length - 1].date, label);
    assert.equal(stats.firstClose, rows[0].close, label);
    assert.equal(stats.lastClose, rows[rows.length - 1].close, label);
    assert.equal(stats.minClose, Math.min(...rows.map((row) => row.close)), label);
    assert.equal(stats.maxClose, Math.max(...rows.map((row) => row.close)), label);
    assert.equal(
      stats.totalVolume,
      rows.reduce((sum, row) => sum + row.volume, 0),
      label,
    );
    assert.equal(stats.averageVolume, stats.totalVolume / rows.length, label);

    // The reported extremes really happened on the reported dates.
    assert.ok(
      rows.some((row) => row.date === stats.minCloseDate && row.close === stats.minClose),
      label,
    );
    assert.ok(
      rows.some((row) => row.date === stats.maxCloseDate && row.close === stats.maxClose),
      label,
    );
    // Every row is inside both the selected range and the reported period.
    for (const row of rows) {
      assert.equal(row.symbol, selection.symbol, label);
      if (selection.from) assert.ok(row.date >= selection.from, label);
      if (selection.to) assert.ok(row.date <= selection.to, label);
      assert.ok(row.date >= stats.firstDate && row.date <= stats.lastDate, label);
    }
  }
});

test('the paginated table covers the filtered rows exactly once', () => {
  const dataset = demoDataset();
  const rows = selectRows(dataset.rows, { symbol: 'DEMO_A', from: '2024-02-01', to: '2024-05-31' });
  const sorted = sortRows(rows, 'date', 'asc');

  for (const pageSize of [10, 25, 50, 100]) {
    const collected = [];
    let page = 1;
    let pageCount = 1;
    do {
      const view = paginate(sorted, page, pageSize);
      pageCount = view.pageCount;
      collected.push(...view.rows);
      page += 1;
    } while (page <= pageCount);

    assert.equal(collected.length, rows.length, `pageSize ${pageSize}`);
    assert.deepEqual(collected, sorted, `pageSize ${pageSize}`);
  }
});

test('sorting the table changes the order but never the set of rows', () => {
  const dataset = demoDataset();
  const rows = selectRows(dataset.rows, { symbol: 'DEMO_B', from: '2024-01-01', to: '2024-03-31' });
  const baseline = computeStats(rows);

  for (const key of ['date', 'close', 'volume']) {
    for (const direction of ['asc', 'desc']) {
      const sorted = sortRows(rows, key, direction);
      assert.equal(sorted.length, rows.length);
      // Same multiset of closes, so the extremes and totals cannot move.
      assert.deepEqual(
        sorted.map((row) => row.close).sort((a, b) => a - b),
        rows.map((row) => row.close).sort((a, b) => a - b),
      );
      assert.equal(
        sorted.reduce((sum, row) => sum + row.volume, 0),
        baseline.totalVolume,
      );
    }
  }
});

test('the exported CSV contains exactly the filtered rows, in the same order', () => {
  const dataset = demoDataset();
  const selection = { symbol: 'DEMO_C', from: '2024-04-01', to: '2024-04-30' };
  const rows = selectRows(dataset.rows, selection);
  const stats = computeStats(rows);

  const { records } = parseCsv(buildCsv(rows));
  assert.deepEqual(records[0].cells, ['date', 'symbol', 'close', 'volume']);
  assert.equal(records.length - 1, stats.count);
  assert.equal(records[1].cells[0], stats.firstDate);
  assert.equal(records[records.length - 1].cells[0], stats.lastDate);
  assert.equal(Number(records[1].cells[2]), stats.firstClose);
  assert.equal(Number(records[records.length - 1].cells[2]), stats.lastClose);
  for (const record of records.slice(1)) {
    assert.equal(record.cells[1], selection.symbol);
    assert.ok(record.cells[0] >= selection.from && record.cells[0] <= selection.to);
  }
});

test('the exported report quotes the same numbers the statistics hold', () => {
  const dataset = demoDataset();
  const selection = { symbol: 'DEMO_A', from: '2024-02-01', to: '2024-08-31' };
  const rows = selectRows(dataset.rows, selection);
  const stats = computeStats(rows);
  const summary = buildSummary({
    symbol: selection.symbol,
    fileName: dataset.fileName,
    isDemo: true,
    requestedRange: selection,
    stats,
  });
  const report = buildTextReport({
    symbol: selection.symbol,
    fileName: dataset.fileName,
    isDemo: true,
    requestedRange: selection,
    stats,
    summary,
    generatedAt: '2026-09-19',
  });

  assert.ok(report.includes(`מספר תצפיות: ${stats.count}`));
  assert.ok(report.includes(formatDate(stats.firstDate)));
  assert.ok(report.includes(formatDate(stats.lastDate)));
  assert.ok(report.includes(formatPercent(stats.percentChange)));
  assert.ok(report.includes(formatPrice(stats.minClose)));
  assert.ok(report.includes(formatPrice(stats.maxClose)));
  // The summary text and the report agree, because both read the same stats.
  assert.ok(summary.paragraphs.join('\n').includes(formatPercent(stats.percentChange)));
});

test('a symbol change moves every derived value together', () => {
  const dataset = demoDataset();
  const perSymbol = dataset.symbols.map((symbol) => {
    const rows = selectRows(dataset.rows, { symbol });
    return { symbol, rows, stats: computeStats(rows), bounds: symbolBounds(dataset.rows, symbol) };
  });

  for (const entry of perSymbol) {
    assert.equal(entry.stats.count, entry.bounds.count, entry.symbol);
    assert.equal(entry.stats.firstDate, entry.bounds.firstDate, entry.symbol);
    assert.equal(entry.stats.lastDate, entry.bounds.lastDate, entry.symbol);
  }
  // Different symbols really do produce different numbers, so a failure to
  // re-render would be visible rather than coincidentally identical.
  const closes = perSymbol.map((entry) => entry.stats.lastClose);
  assert.equal(new Set(closes).size, closes.length);
});

test('the sum over every symbol equals the whole imported dataset', () => {
  const dataset = demoDataset();
  const total = dataset.symbols.reduce(
    (sum, symbol) => sum + selectRows(dataset.rows, { symbol }).length,
    0,
  );
  assert.equal(total, dataset.rowCount);
});
