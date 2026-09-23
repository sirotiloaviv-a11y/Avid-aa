import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchAssets, filterNews, filterAlerts, mergeAlerts } from '../src/js/data/filters.js';
import { buildDemoDataset } from '../src/js/data/demoData.js';
import { createStore, STORAGE_KEY } from '../src/js/store.js';
import {
  dateKey, addDays, weekKeys, formatPct, formatPrice, tzOffset, isValidDateKey,
} from '../src/js/format.js';

const ds = buildDemoDataset(new Date('2026-09-23T15:00:00Z'));

test('asset search matches symbol and Hebrew name, filtered by type', () => {
  assert.deepEqual(searchAssets(ds.assets, { query: 'orl' }).map((a) => a.symbol), ['ORLN']);
  assert.deepEqual(searchAssets(ds.assets, { query: 'נובה' }).map((a) => a.symbol), ['NOVX']);
  assert.equal(searchAssets(ds.assets, { type: 'crypto' }).length, 4);
  assert.equal(searchAssets(ds.assets, { query: 'ORLN', type: 'crypto' }).length, 0);
  assert.equal(searchAssets(ds.assets, { query: '  ' }).length, ds.assets.length);
});

test('news filter by asset and category', () => {
  const byAsset = filterNews(ds.news, { symbol: 'ORLN' });
  assert.ok(byAsset.length > 0 && byAsset.every((n) => n.symbols.includes('ORLN')));
  const both = filterNews(ds.news, { symbol: 'ORLN', category: 'דוחות כספיים' });
  assert.ok(both.every((n) => n.category === 'דוחות כספיים'));
  assert.equal(filterNews(ds.news, { symbol: 'SHKD', category: 'רגולציה' }).length, 0);
});

test('alert filters and merge', () => {
  const first = ds.alerts[0];
  const readIds = { [first.id]: true };
  assert.ok(!filterAlerts(ds.alerts, { status: 'unread', readIds }).includes(first));
  assert.deepEqual(filterAlerts(ds.alerts, { status: 'read', readIds }), [first]);
  assert.ok(filterAlerts(ds.alerts, { types: ['news'] }).every((a) => a.type === 'news'));
  const manual = { ...first, id: 'm1', time: first.time + 1 };
  const merged = mergeAlerts(ds.alerts, [manual, manual]);
  assert.equal(merged.length, ds.alerts.length + 1);
  assert.equal(merged[0].id, 'm1');
});

function memoryStorage() {
  const m = new Map();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
}

test('store persists watchlist, prefs and reminders', () => {
  const storage = memoryStorage();
  const s = createStore(storage);
  s.toggleWatch('TVLA');
  s.toggleWatch('ORLN');
  s.setPrefs({ timeZone: 'UTC', alertTypes: { volume: false } });
  s.toggleReminder('e05');
  s.markRead(['x']);
  const again = createStore(storage);
  assert.ok(again.isWatched('TVLA'));
  assert.ok(!again.isWatched('ORLN'));
  assert.equal(again.get().prefs.timeZone, 'UTC');
  assert.deepEqual(again.enabledAlertTypes(), ['price', 'news']);
  assert.ok(again.hasReminder('e05'));
  again.reset();
  assert.ok(createStore(storage).isWatched('ORLN'));
});

test('store survives corrupt or missing storage', () => {
  const storage = memoryStorage();
  storage.setItem(STORAGE_KEY, '{not json');
  assert.ok(createStore(storage).get().watchlist.length > 0);
  const s = createStore(null);
  s.toggleWatch('TVLA');
  assert.ok(s.isWatched('TVLA'));
  assert.equal(s.isPersistent(), false);
});

test('date helpers respect the time zone', () => {
  const t = Date.parse('2026-09-23T22:30:00Z');
  assert.equal(dateKey(t, 'UTC'), '2026-09-23');
  assert.equal(dateKey(t, 'Asia/Jerusalem'), '2026-09-24');
  assert.equal(addDays('2026-09-30', 1), '2026-10-01');
  const week = weekKeys('2026-09-23');
  assert.equal(week[0], '2026-09-20');
  assert.equal(week.length, 7);
  assert.equal(tzOffset('UTC'), 'UTC+00:00');
  assert.equal(tzOffset('Asia/Jerusalem', t), 'UTC+03:00');
  assert.ok(isValidDateKey('2026-09-23'));
  assert.ok(!isValidDateKey('23/09/2026'));
});

test('number formatting', () => {
  assert.equal(formatPct(1.234), '+1.23%');
  assert.equal(formatPct(-5.8), '−5.80%');
  assert.equal(formatPrice(1840.5), '$1,840.50');
  assert.equal(formatPrice(0.84213), '$0.8421');
});
