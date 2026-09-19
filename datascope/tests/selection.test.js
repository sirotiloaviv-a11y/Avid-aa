import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeRange,
  paginate,
  searchSymbols,
  selectRows,
  sortRows,
  symbolBounds,
} from '../src/lib/selection.js';
import { validateDataset } from '../src/lib/validate.js';

const FIXTURE = [
  '2024-01-02,AAA,100,10',
  '2024-01-03,AAA,101,20',
  '2024-02-01,AAA,105,30',
  '2024-03-01,AAA,110,40',
  '2024-01-02,BBB,50,5',
  '2024-02-01,BBB,45,6',
  '2024-01-15,CCC,7.5,0',
].join('\n');

function dataset() {
  const result = validateDataset(`date,symbol,close,volume\n${FIXTURE}\n`, { fileName: 'f.csv' });
  assert.equal(result.ok, true);
  return result.dataset;
}

test('selecting a symbol returns only that symbol, in date order', () => {
  const rows = selectRows(dataset().rows, { symbol: 'AAA' });
  assert.equal(rows.length, 4);
  assert.ok(rows.every((row) => row.symbol === 'AAA'));
  assert.deepEqual(
    rows.map((row) => row.date),
    ['2024-01-02', '2024-01-03', '2024-02-01', '2024-03-01'],
  );
});

test('no symbol selected means no rows', () => {
  assert.deepEqual(selectRows(dataset().rows, {}), []);
  assert.deepEqual(selectRows(dataset().rows, { symbol: null }), []);
});

test('an unknown symbol yields an empty selection rather than an error', () => {
  assert.deepEqual(selectRows(dataset().rows, { symbol: 'ZZZ' }), []);
});

test('the date range is inclusive at both ends', () => {
  const rows = selectRows(dataset().rows, { symbol: 'AAA', from: '2024-01-03', to: '2024-02-01' });
  assert.deepEqual(
    rows.map((row) => row.date),
    ['2024-01-03', '2024-02-01'],
  );
});

test('an open-ended range filters only the side that is given', () => {
  const fromOnly = selectRows(dataset().rows, { symbol: 'AAA', from: '2024-02-01' });
  assert.deepEqual(
    fromOnly.map((row) => row.date),
    ['2024-02-01', '2024-03-01'],
  );
  const toOnly = selectRows(dataset().rows, { symbol: 'AAA', to: '2024-01-03' });
  assert.deepEqual(
    toOnly.map((row) => row.date),
    ['2024-01-02', '2024-01-03'],
  );
});

test('a range with no observations in it returns nothing, which is not an error', () => {
  const rows = selectRows(dataset().rows, { symbol: 'AAA', from: '2024-01-04', to: '2024-01-31' });
  assert.deepEqual(rows, []);
});

test('a range narrowed to one day yields one observation', () => {
  const rows = selectRows(dataset().rows, { symbol: 'AAA', from: '2024-02-01', to: '2024-02-01' });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].close, 105);
});

test('date comparison is string-based, so it is timezone-independent', () => {
  // Same selection under two very different process timezones.
  const original = process.env.TZ;
  const run = (tz) => {
    process.env.TZ = tz;
    return selectRows(dataset().rows, { symbol: 'AAA', from: '2024-01-02', to: '2024-01-02' }).map(
      (row) => row.date,
    );
  };
  try {
    assert.deepEqual(run('Pacific/Kiritimati'), ['2024-01-02']);
    assert.deepEqual(run('Pacific/Midway'), ['2024-01-02']);
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test('symbolBounds reports the real first and last dates per symbol', () => {
  const rows = dataset().rows;
  assert.deepEqual(symbolBounds(rows, 'AAA'), {
    firstDate: '2024-01-02',
    lastDate: '2024-03-01',
    count: 4,
  });
  assert.deepEqual(symbolBounds(rows, 'CCC'), {
    firstDate: '2024-01-15',
    lastDate: '2024-01-15',
    count: 1,
  });
  assert.equal(symbolBounds(rows, 'ZZZ'), null);
});

test('symbol search is case-insensitive and ranks prefix matches first', () => {
  const symbols = ['AAPL', 'BAA', 'AA', 'ZAAZ'];
  assert.deepEqual(searchSymbols(symbols, 'aa'), ['AAPL', 'AA', 'BAA', 'ZAAZ']);
  assert.deepEqual(searchSymbols(symbols, ''), symbols);
  assert.deepEqual(searchSymbols(symbols, '   '), symbols);
  assert.deepEqual(searchSymbols(symbols, 'qqq'), []);
});

test('sortRows sorts by each column in both directions without mutating', () => {
  const rows = selectRows(dataset().rows, { symbol: 'AAA' });
  const byVolumeDesc = sortRows(rows, 'volume', 'desc');
  assert.deepEqual(
    byVolumeDesc.map((row) => row.volume),
    [40, 30, 20, 10],
  );
  const byCloseAsc = sortRows(rows, 'close', 'asc');
  assert.deepEqual(
    byCloseAsc.map((row) => row.close),
    [100, 101, 105, 110],
  );
  const byDateDesc = sortRows(rows, 'date', 'desc');
  assert.equal(byDateDesc[0].date, '2024-03-01');
  // The source array is untouched.
  assert.equal(rows[0].date, '2024-01-02');
});

test('pagination clamps the page and reports the visible span', () => {
  const rows = Array.from({ length: 23 }, (_, i) => ({ date: `2024-01-${i + 1}`, close: i, volume: i }));
  const first = paginate(rows, 1, 10);
  assert.equal(first.rows.length, 10);
  assert.equal(first.pageCount, 3);
  assert.equal(first.firstIndex, 1);
  assert.equal(first.lastIndex, 10);

  const last = paginate(rows, 3, 10);
  assert.equal(last.rows.length, 3);
  assert.equal(last.firstIndex, 21);
  assert.equal(last.lastIndex, 23);

  const clampedHigh = paginate(rows, 99, 10);
  assert.equal(clampedHigh.page, 3);
  const clampedLow = paginate(rows, 0, 10);
  assert.equal(clampedLow.page, 1);

  const empty = paginate([], 1, 10);
  assert.equal(empty.pageCount, 1);
  assert.equal(empty.total, 0);
  assert.equal(empty.firstIndex, 0);
  assert.equal(empty.lastIndex, 0);
});

test('an inverted range is flagged instead of silently returning rows', () => {
  const range = normalizeRange({ from: '2024-03-01', to: '2024-01-01' });
  assert.equal(range.inverted, true);
  const ok = normalizeRange({ from: '2024-01-01', to: '2024-03-01' });
  assert.equal(ok.inverted, false);
  assert.equal(normalizeRange({}).inverted, false);
  assert.deepEqual(normalizeRange({ from: '', to: '' }), { from: null, to: null, inverted: false });
});
