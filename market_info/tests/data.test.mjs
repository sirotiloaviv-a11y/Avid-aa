import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildDemoDataset, makeManualDemoAlert, ASSETS, PRICE_ALERT_THRESHOLD_PCT, VOLUME_ALERT_MULTIPLE,
} from '../src/js/data/demoData.js';
import { DemoProvider } from '../src/js/data/demoProvider.js';

const NOW = new Date('2026-09-23T15:00:00Z');

test('dataset is deterministic for the same anchor time', () => {
  assert.deepEqual(buildDemoDataset(NOW), buildDemoDataset(NOW));
});

test('asset summaries match the last bars of their history', () => {
  const ds = buildDemoDataset(NOW);
  for (const a of ds.assets) {
    const h = ds.histories[a.symbol];
    assert.equal(a.price, h.at(-1).close);
    assert.equal(a.previousClose, h.at(-2).close);
    assert.equal(a.volume, h.at(-1).volume);
    assert.ok(h.every((b) => b.t <= NOW.getTime()), `${a.symbol} has a bar in the future`);
  }
});

test('stock bars skip weekends and crypto bars do not', () => {
  const ds = buildDemoDataset(NOW);
  const days = (s) => ds.histories[s].map((b) => new Date(b.t).getUTCDay());
  assert.ok(!days('ORLN').some((d) => d === 0 || d === 6));
  assert.ok(days('NOVX').some((d) => d === 0 || d === 6));
});

test('generated alerts are backed by the data they cite', () => {
  const ds = buildDemoDataset(NOW);
  assert.ok(ds.alerts.length > 0);
  for (const al of ds.alerts) {
    assert.ok(ds.assets.some((a) => a.symbol === al.symbol));
    if (al.type === 'price') {
      assert.ok(Math.abs(al.trigger.changePct) >= PRICE_ALERT_THRESHOLD_PCT);
      const bar = ds.histories[al.symbol].find((b) => b.t === al.time);
      assert.equal(bar.close, al.trigger.toPrice);
    }
    if (al.type === 'volume') assert.ok(al.trigger.ratio >= VOLUME_ALERT_MULTIPLE);
    if (al.type === 'news') assert.ok(ds.news.some((n) => n.id === al.trigger.newsId));
  }
  const types = new Set(ds.alerts.map((a) => a.type));
  assert.deepEqual([...types].sort(), ['news', 'price', 'volume']);
});

test('every pinned shock produces the expected price alert', () => {
  const ds = buildDemoDataset(NOW);
  for (const a of ASSETS.filter((x) => x.shock && Math.abs(x.shock.move) * 100 >= PRICE_ALERT_THRESHOLD_PCT)) {
    assert.ok(ds.alerts.some((al) => al.type === 'price' && al.symbol === a.symbol), a.symbol);
  }
});

test('news and events reference only known assets and are marked demo', () => {
  const ds = buildDemoDataset(NOW);
  const symbols = new Set(ds.assets.map((a) => a.symbol));
  for (const n of ds.news) {
    assert.equal(n.demo, true);
    n.symbols.forEach((s) => assert.ok(symbols.has(s), s));
    assert.ok(!/https?:\/\//.test(n.summary + n.title), 'news must not link to articles');
  }
  for (const e of ds.events) e.symbols.forEach((s) => assert.ok(symbols.has(s), s));
});

test('manual demo alert respects enabled types', () => {
  const ds = buildDemoDataset(NOW);
  for (let i = 0; i < 20; i++) {
    const a = makeManualDemoAlert(ds, ['volume']);
    assert.equal(a.type, 'volume');
    assert.equal(a.manual, true);
  }
  assert.equal(makeManualDemoAlert(ds, []), null);
});

test('provider returns copies and can simulate failure', async () => {
  let fail = false;
  const p = new DemoProvider({ now: NOW, latencyMs: 0, shouldFail: () => fail });
  const a = await p.getAssets();
  a[0].price = -1;
  assert.notEqual((await p.getAssets())[0].price, -1);
  assert.equal((await p.getPriceHistory('ORLN', 7)).length, 7);
  assert.equal(await p.getAsset('NOPE'), null);
  const info = await p.getSourceInfo();
  assert.equal(info.isLive, false);
  fail = true;
  await assert.rejects(p.getAssets());
});
