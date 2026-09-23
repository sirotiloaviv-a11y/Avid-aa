import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { avDaily, cgMarkets, cgChart, fakeFetch } from './fixtures/make.mjs';
import { mapDailySeries, classifyPayload } from '../server/providers/alphaVantage.mjs';
import { mapMarkets, mapMarketChart } from '../server/providers/coinGecko.mjs';
import { loadConfig, parseEnvFile } from '../server/config.mjs';
import { MarketCache } from '../server/cache.mjs';
import { RequestBudget } from '../server/budget.mjs';
import { createMarketService, quoteFromBars } from '../server/marketService.mjs';
import {
  usMarketSession, lastCompletedSessionDate, isStockSeriesOld, zonedTimeToUtc,
} from '../server/time.mjs';
import { createAppServer } from '../server.mjs';

// Tuesday 2026-09-22, 14:00 New York (EDT, UTC-4): market open.
const OPEN_NOW = Date.parse('2026-09-22T18:00:00Z');
// Saturday 2026-09-26, noon New York: market closed.
const WEEKEND_NOW = Date.parse('2026-09-26T16:00:00Z');

const isAv = (u) => u.hostname === 'av.test';
const isCg = (u) => u.hostname === 'cg.test';

function config(overrides = {}) {
  return loadConfig({
    env: {
      ALPHA_VANTAGE_API_KEY: 'av-test-key',
      COINGECKO_DEMO_API_KEY: 'cg-test-key',
      ALPHA_VANTAGE_BASE_URL: 'https://av.test/query',
      COINGECKO_BASE_URL: 'https://cg.test/api/v3',
      MARKET_STOCK_SYMBOLS: 'AAPL=Apple,MSFT',
      MARKET_CRYPTO_ASSETS: 'BTC=bitcoin,ETH=ethereum',
      ...overrides,
    },
  });
}

function service({ routes, now = OPEN_NOW, cfg = config(), cache } = {}) {
  const clock = { t: now };
  const f = fakeFetch(routes);
  const svc = createMarketService({ config: cfg, fetchImpl: f.impl, cache: cache ?? new MarketCache({ now: () => clock.t }), now: () => clock.t });
  return { svc, calls: f.calls, clock };
}

const defaultRoutes = () => [
  [isAv, (u) => ({ body: avDaily(u.searchParams.get('symbol'), '2026-09-21', 30) })],
  [(u) => isCg(u) && u.pathname.endsWith('/coins/markets'),
    () => ({ body: cgMarkets([['bitcoin', 'btc', 'Bitcoin', 60000, 600], ['ethereum', 'eth', 'Ethereum', 3000, -30]], '2026-09-22T17:58:00.000Z') })],
  [(u) => isCg(u) && u.pathname.includes('/market_chart'), () => ({ body: cgChart(OPEN_NOW) })],
];

// ---------- mapping ----------

test('Alpha Vantage daily series maps to ascending bars at 16:00 New York', () => {
  const m = mapDailySeries(avDaily('AAPL', '2026-09-21', 5), 'AAPL');
  assert.equal(m.bars.length, 5);
  assert.ok(m.bars.every((b, i) => i === 0 || b.t > m.bars[i - 1].t));
  assert.equal(new Date(m.bars.at(-1).t).toISOString(), '2026-09-21T20:00:00.000Z');
  assert.equal(m.bars.at(-1).close, 104);
  assert.equal(m.bars.at(-1).volume, 1_004_000);
});

test('Alpha Vantage: winter dates use EST', () => {
  const m = mapDailySeries(avDaily('AAPL', '2026-01-15', 2), 'AAPL');
  assert.equal(new Date(m.bars.at(-1).t).toISOString(), '2026-01-15T21:00:00.000Z');
});

test('Alpha Vantage: bad rows are dropped, missing volume stays null, nothing invented', () => {
  const body = avDaily('AAPL', '2026-09-21', 3);
  const dates = Object.keys(body['Time Series (Daily)']);
  body['Time Series (Daily)'][dates[0]]['4. close'] = 'n/a';
  delete body['Time Series (Daily)'][dates[1]]['5. volume'];
  const m = mapDailySeries(body, 'AAPL');
  assert.equal(m.bars.length, 2);
  assert.equal(m.dropped, 1);
  assert.equal(m.bars[0].volume, null);
});

test('Alpha Vantage: HTTP-200 error bodies are classified', () => {
  const code = (body) => { try { classifyPayload(body, 'X'); return 'ok'; } catch (e) { return e.code; } };
  assert.equal(code({ 'Error Message': 'Invalid API call.' }), 'invalid_symbol');
  assert.equal(code({ Note: 'Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute.' }), 'rate_limited');
  assert.equal(code({ Information: 'We have detected your API key as ... standard API rate limit is 25 requests per day.' }), 'rate_limited');
  assert.equal(code({ Information: 'This is a premium endpoint.' }), 'premium_required');
  assert.equal(code({ Information: 'the parameter apikey is invalid or missing.' }), 'auth_failed');
  assert.equal(code(null), 'bad_response');
});

test('CoinGecko markets and chart mapping', () => {
  const m = mapMarkets(cgMarkets([['bitcoin', 'btc', 'Bitcoin', 60000, 600]], '2026-09-22T17:58:00.000Z'));
  const btc = m.get('bitcoin');
  assert.equal(btc.ticker, 'BTC');
  assert.equal(btc.previousClose, 59400);
  assert.ok(Math.abs(btc.changePct - 1.0101) < 0.001);
  assert.equal(btc.asOf, Date.parse('2026-09-22T17:58:00Z'));
  const chart = mapMarketChart({ prices: [[2, 11], [1, 10], [1, 10], [3, null]], total_volumes: [[1, 5]] });
  assert.deepEqual(chart.bars.map((b) => b.t), [1, 2]);
  assert.equal(chart.bars[0].open, null, 'no candles are synthesized');
  assert.equal(chart.bars[1].volume, null, 'missing volume is not synthesized');
});

test('quote calculations from bars', () => {
  const bars = Array.from({ length: 21 }, (_, i) => ({ close: 100 + i, volume: 1000 + i }));
  const q = quoteFromBars(bars);
  assert.equal(q.price, 120);
  assert.equal(q.previousClose, 119);
  assert.equal(q.change, 1);
  assert.ok(Math.abs(q.changePct - 100 / 119) < 1e-9);
  assert.equal(q.avgVolume20, 1009.5);
  assert.equal(quoteFromBars(bars.slice(0, 10)).avgVolume20, null);
  assert.equal(quoteFromBars(bars.slice(0, 1)).change, null);
});

// ---------- time ----------

test('US session status and staleness', () => {
  assert.equal(usMarketSession(OPEN_NOW).state, 'open');
  assert.deepEqual(usMarketSession(WEEKEND_NOW), { state: 'closed', reason: 'weekend' });
  assert.equal(usMarketSession(Date.parse('2026-09-22T13:00:00Z')).reason, 'pre_open');
  assert.equal(usMarketSession(Date.parse('2026-09-22T20:30:00Z')).reason, 'after_close');
  assert.equal(lastCompletedSessionDate(OPEN_NOW), '2026-09-21');
  assert.equal(lastCompletedSessionDate(WEEKEND_NOW), '2026-09-25');
  assert.equal(isStockSeriesOld('2026-09-24', WEEKEND_NOW), false, 'one missing session is tolerated');
  assert.equal(isStockSeriesOld('2026-09-22', WEEKEND_NOW), true);
  assert.equal(new Date(zonedTimeToUtc('2026-03-09', 16, 0, 'America/New_York')).toISOString(), '2026-03-09T20:00:00.000Z');
});

// ---------- config ----------

test('config: .env parsing, defaults, invalid entries dropped', () => {
  assert.deepEqual(parseEnvFile('# c\nA=1\nB="two"\n\nbad\n'), { A: '1', B: 'two' });
  const cfg = loadConfig({ env: { MARKET_STOCK_SYMBOLS: 'aapl,bad symbol', MARKET_CRYPTO_ASSETS: 'BTC=bitcoin,X=Bad Id' } });
  assert.deepEqual(cfg.stocks.map((s) => s.symbol), ['AAPL']);
  assert.deepEqual(cfg.crypto.map((c) => c.id), ['bitcoin']);
  assert.equal(cfg.warnings.length, 2);
  assert.equal(cfg.alphaVantage.apiKey, '');
  assert.equal(cfg.alphaVantage.perDay, 25);
  const dir = mkdtempSync(join(tmpdir(), 'mi-'));
  writeFileSync(join(dir, '.env'), 'ALPHA_VANTAGE_API_KEY=from-file\n');
  assert.equal(loadConfig({ env: {}, envFile: join(dir, '.env') }).alphaVantage.apiKey, 'from-file');
  assert.equal(loadConfig({ env: { ALPHA_VANTAGE_API_KEY: 'env-wins' }, envFile: join(dir, '.env') }).alphaVantage.apiKey, 'env-wins');
});

// ---------- service ----------

test('stock quote carries source, data time, delay and market state', async () => {
  const { svc, calls } = service({ routes: defaultRoutes() });
  const q = await svc.quote('aapl');
  assert.equal(q.symbol, 'AAPL');
  assert.equal(q.name, 'Apple');
  assert.equal(q.price, 129);
  assert.equal(q.change, 1);
  assert.equal(q.meta.source.name, 'Alpha Vantage');
  assert.equal(q.meta.delay, 'end_of_day');
  assert.equal(q.meta.asOf, Date.parse('2026-09-21T20:00:00Z'));
  assert.equal(q.meta.marketState, 'open');
  assert.equal(q.meta.stale, false);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.searchParams.get('apikey'), 'av-test-key');
  assert.equal(calls[0].url.searchParams.get('function'), 'TIME_SERIES_DAILY');
});

test('crypto quote uses 24h basis, attribution and demo-key header', async () => {
  const { svc, calls } = service({ routes: defaultRoutes() });
  const q = await svc.quote('BTC');
  assert.equal(q.price, 60000);
  assert.equal(q.meta.changeBasis, '24h');
  assert.equal(q.meta.source.attribution, 'Powered by CoinGecko');
  assert.equal(q.meta.delay, 'delayed');
  assert.equal(calls[0].headers['x-cg-demo-api-key'], 'cg-test-key');
  const h = await svc.history('BTC');
  assert.equal(h.bars[0].open, null);
  assert.equal(h.meta.candles, false);
});

test('cache: second request is served from cache without calling the provider', async () => {
  const { svc, calls, clock } = service({ routes: defaultRoutes() });
  await svc.quote('AAPL');
  await svc.history('AAPL');
  await svc.quote('AAPL');
  assert.equal(calls.length, 1);
  clock.t += 7 * 3600000;
  await svc.quote('AAPL');
  assert.equal(calls.length, 2, 'refetched after TTL');
});

test('concurrent identical requests share one provider call', async () => {
  const { svc, calls } = service({ routes: defaultRoutes() });
  await Promise.all([svc.quote('AAPL'), svc.quote('AAPL'), svc.history('AAPL')]);
  assert.equal(calls.length, 1);
});

test('provider failure after TTL serves the old copy marked stale with its time', async () => {
  let fail = false;
  const routes = [[isAv, (u) => (fail ? new Error('socket hang up') : { body: avDaily(u.searchParams.get('symbol'), '2026-09-21', 30) })]];
  const { svc, clock } = service({ routes });
  const first = await svc.quote('AAPL');
  fail = true;
  clock.t += 7 * 3600000;
  const second = await svc.quote('AAPL');
  assert.equal(second.meta.stale, true);
  assert.equal(second.meta.staleReason, 'fetch_failed');
  assert.equal(second.meta.fetchedAt, first.meta.fetchedAt);
  assert.match(second.meta.warning, /אין חיבור/);
});

test('failure with no cached copy is an error, never substitute data', async () => {
  const { svc } = service({ routes: [[isAv, () => new Error('down')]] });
  await assert.rejects(svc.quote('AAPL'), (e) => e.code === 'network');
  const { svc: s2 } = service({ routes: [[isAv, () => ({ status: 503, body: {} })]] });
  await assert.rejects(s2.quote('AAPL'), (e) => e.code === 'upstream_unavailable');
});

test('invalid symbols and bad formats', async () => {
  const { svc, calls } = service({ routes: [[isAv, () => ({ body: { 'Error Message': 'Invalid API call.' } })]] });
  await assert.rejects(svc.quote('ZZZZ'), (e) => e.code === 'invalid_symbol' && e.status === 404);
  await assert.rejects(svc.quote('../etc'), (e) => e.code === 'bad_symbol_format');
  await assert.rejects(svc.quote(''), (e) => e.code === 'bad_symbol_format');
  assert.equal(calls.length, 1, 'malformed symbols never reach the provider');
});

test('missing keys report not_configured without any network call', async () => {
  const { svc, calls } = service({ routes: defaultRoutes(), cfg: config({ ALPHA_VANTAGE_API_KEY: '', COINGECKO_DEMO_API_KEY: '' }) });
  await assert.rejects(svc.quote('AAPL'), (e) => e.code === 'not_configured');
  await assert.rejects(svc.quote('BTC'), (e) => e.code === 'not_configured');
  const list = await svc.assets();
  assert.ok(list.every((a) => a.error?.code === 'not_configured'));
  assert.equal(calls.length, 0);
  const st = svc.status();
  assert.equal(st.providers.stocks.configured, false);
  assert.ok(!JSON.stringify(st).includes('test-key'));
});

test('local quota stops calls before the provider limit', async () => {
  const cfg = config({ ALPHA_VANTAGE_PER_MINUTE: '2', MARKET_STOCK_SYMBOLS: 'AAPL,MSFT,NVDA' });
  const { svc, calls } = service({ routes: defaultRoutes(), cfg });
  const list = await svc.assets();
  assert.equal(calls.filter((c) => isAv(c.url)).length, 2);
  const nvda = list.find((a) => a.symbol === 'NVDA');
  assert.equal(nvda.error.code, 'rate_limited');
  assert.ok(nvda.error.retryAfterSec > 0);
});

test('provider 429 blocks further calls for Retry-After seconds', async () => {
  const routes = [[isCg, () => ({ status: 429, headers: { 'retry-after': '120' }, body: {} })]];
  const { svc, calls, clock } = service({ routes });
  await assert.rejects(svc.quote('BTC'), (e) => e.code === 'rate_limited');
  await assert.rejects(svc.quote('ETH'), (e) => e.code === 'rate_limited' && e.retryAfterSec <= 120);
  assert.equal(calls.length, 1);
  clock.t += 121000;
  await assert.rejects(svc.quote('BTC'));
  assert.equal(calls.length, 2);
});

test('a non-JSON 403 from a proxy is a blocked connection, not a rejected key', async () => {
  const proxy403 = () => ({ status: 403, headers: { 'content-type': 'text/plain' }, body: 'Host not in allowlist' });
  const { svc } = service({ routes: [[isAv, proxy403], [isCg, proxy403]] });
  await assert.rejects(svc.quote('AAPL'), (e) => e.code === 'network' && /נחסמה בדרך/.test(e.message));
  await assert.rejects(svc.quote('BTC'), (e) => e.code === 'network');
  const json401 = () => ({ status: 401, body: { status: { error_code: 10002, error_message: 'API Key Missing' } } });
  const { svc: s2 } = service({ routes: [[isCg, json401]] });
  await assert.rejects(s2.quote('BTC'), (e) => e.code === 'auth_failed');
});

test('rate-limit message in a 200 body is treated as rate limiting', async () => {
  const routes = [[isAv, () => ({ body: { Information: 'standard API rate limit is 25 requests per day' } })]];
  const { svc } = service({ routes });
  await assert.rejects(svc.quote('AAPL'), (e) => e.code === 'rate_limited');
});

test('closed market vs old data vs fetch failure are distinct', async () => {
  const { svc } = service({ routes: defaultRoutes(), now: Date.parse('2026-09-22T12:00:00Z') });
  const q = await svc.quote('AAPL');
  assert.equal(q.meta.marketState, 'closed');
  assert.equal(q.meta.stale, false);
  const old = service({ routes: [[isAv, (u) => ({ body: avDaily('AAPL', '2026-09-10', 30) })]], now: OPEN_NOW });
  const q2 = await old.svc.quote('AAPL');
  assert.equal(q2.meta.stale, true);
  assert.equal(q2.meta.staleReason, 'old_data');
});

test('today\'s bar during the session is flagged partial', async () => {
  const { svc } = service({ routes: [[isAv, () => ({ body: avDaily('AAPL', '2026-09-22', 30) })]] });
  assert.equal((await svc.quote('AAPL')).meta.partial, true);
});

test('crypto quote older than 30 minutes is flagged old', async () => {
  const routes = [[isCg, () => ({ body: cgMarkets([['bitcoin', 'btc', 'Bitcoin', 1, 0], ['ethereum', 'eth', 'E', 1, 0]], '2026-09-22T16:00:00Z') })]];
  const { svc } = service({ routes });
  const q = await svc.quote('BTC');
  assert.equal(q.meta.staleReason, 'old_data');
});

test('crypto coin missing from the answer is an invalid symbol, others still load', async () => {
  const routes = [[isCg, () => ({ body: cgMarkets([['bitcoin', 'btc', 'Bitcoin', 1, 0]], '2026-09-22T17:58:00Z') })]];
  const { svc } = service({ routes });
  const list = await svc.assets();
  assert.equal(list.find((a) => a.symbol === 'BTC').price, 1);
  assert.equal(list.find((a) => a.symbol === 'ETH').error.code, 'invalid_symbol');
});

test('cache and quota counters persist across restarts', async () => {
  const file = join(mkdtempSync(join(tmpdir(), 'mi-')), 'cache.json');
  const a = service({ routes: defaultRoutes(), cache: new MarketCache({ file, now: () => OPEN_NOW }) });
  await a.svc.quote('AAPL');
  const saved = JSON.parse(readFileSync(file, 'utf8'));
  assert.equal(saved.meta.usage.alpha_vantage.dayCount, 1);
  const b = service({ routes: defaultRoutes(), cache: new MarketCache({ file, now: () => OPEN_NOW }) });
  await b.svc.quote('AAPL');
  assert.equal(b.calls.length, 0);
  assert.ok(!readFileSync(file, 'utf8').includes('av-test-key'), 'keys are not written to the cache');
});

test('budget windows', () => {
  const clock = { t: Date.parse('2026-09-22T23:59:00Z') };
  const b = new RequestBudget({ name: 'x', perDay: 1, cache: new MarketCache(), now: () => clock.t });
  assert.ok(b.tryConsume().ok);
  const denied = b.tryConsume();
  assert.equal(denied.scope, 'day');
  assert.ok(denied.retryAfterSec <= 60);
  clock.t += 120000;
  assert.ok(b.tryConsume().ok, 'new UTC day resets');
});

// ---------- HTTP ----------

test('HTTP API returns JSON, maps errors to status codes, keeps keys server-side', async () => {
  const { svc } = service({ routes: defaultRoutes() });
  const server = createAppServer(join(import.meta.dirname, '..', 'src'), { market: svc });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const st = await fetch(`${base}/api/market/status`);
    assert.equal(st.status, 200);
    const stText = await st.text();
    assert.ok(!stText.includes('test-key'));
    const q = await (await fetch(`${base}/api/market/quote?symbol=AAPL`)).json();
    assert.equal(q.price, 129);
    const bad = await fetch(`${base}/api/market/quote?symbol=%3Cscript%3E`);
    assert.equal(bad.status, 400);
    assert.equal((await bad.json()).error.code, 'bad_symbol_format');
    const hist = await (await fetch(`${base}/api/market/history?symbol=ETH`)).json();
    assert.ok(hist.bars.length > 0);
    const assets = await (await fetch(`${base}/api/market/assets`)).json();
    assert.equal(assets.assets.length, 4);
    assert.equal((await fetch(`${base}/api/market/nope`)).status, 404);
    assert.equal((await fetch(`${base}/`)).status, 200, 'static files still served');
  } finally {
    server.close();
  }
});
