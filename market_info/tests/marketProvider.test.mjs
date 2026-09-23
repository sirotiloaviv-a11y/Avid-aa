import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MarketProvider } from '../src/js/data/marketProvider.js';
import { createProvider } from '../src/js/data/provider.js';

function fake(map) {
  const calls = [];
  const impl = async (url) => {
    calls.push(url);
    const path = url.replace('/api/market/', '');
    const r = map[path] ?? map[path.split('?')[0]];
    if (r instanceof Error) throw r;
    if (!r) return { ok: false, status: 404, json: async () => ({ error: { code: 'not_found', message: 'x' } }) };
    return { ok: (r.status ?? 200) < 400, status: r.status ?? 200, json: async () => r.body };
  };
  return { impl, calls };
}

test('market provider exposes no news/events/alerts and never returns demo content', async () => {
  const p = new MarketProvider({ fetchImpl: fake({}).impl });
  assert.deepEqual(p.capabilities, { news: false, events: false, alerts: false, demoTrigger: false });
  assert.deepEqual(await p.getNews(), []);
  assert.deepEqual(await p.getEvents(), []);
  assert.deepEqual(await p.getAlerts(), []);
  assert.equal(await p.createDemoAlert(['price']), null);
});

test('errors carry the server code; unknown symbols become null', async () => {
  const f = fake({
    'quote?symbol=ZZZ': { status: 404, body: { error: { code: 'invalid_symbol', message: 'לא נמצא' } } },
    'quote?symbol=AAPL': { status: 503, body: { error: { code: 'not_configured', message: 'נדרשת הגדרה' } } },
    assets: { body: { assets: [{ symbol: 'AAPL' }] } },
  });
  const p = new MarketProvider({ fetchImpl: f.impl });
  assert.equal(await p.getAsset('ZZZ'), null);
  await assert.rejects(p.getAsset('AAPL'), (e) => e.code === 'not_configured' && e.message === 'נדרשת הגדרה');
  assert.equal((await p.getAssets()).length, 1);
});

test('server unreachable is reported distinctly', async () => {
  const p = new MarketProvider({ fetchImpl: fake({ status: new TypeError('fetch failed') }).impl });
  await assert.rejects(p.getStatus(), (e) => e.code === 'server_unreachable');
});

test('history is cached briefly and sliced to the requested range', async () => {
  const bars = Array.from({ length: 100 }, (_, i) => ({ t: i, close: i }));
  const f = fake({ 'history?symbol=AAPL': { body: { bars, meta: {} } } });
  const p = new MarketProvider({ fetchImpl: f.impl });
  assert.equal((await p.getPriceHistory('AAPL', 7)).length, 7);
  assert.equal((await p.getPriceHistory('AAPL', 90)).length, 90);
  assert.equal(f.calls.length, 1);
});

test('factory picks provider by mode', () => {
  assert.equal(createProvider('market').mode, 'market');
  assert.equal(createProvider('demo', { latencyMs: 0 }).mode, 'demo');
  assert.equal(createProvider().mode, 'demo');
});
