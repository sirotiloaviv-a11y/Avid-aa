import { test } from 'node:test';
import assert from 'node:assert/strict';
import { avDaily, cgMarkets, cgChart, fakeFetch } from './fixtures/make.mjs';
import { loadConfig } from '../server/config.mjs';
import { MarketCache } from '../server/cache.mjs';
import { runConnectionCheck, redact, overallStatus } from '../server/connectionCheck.mjs';
import { formatReport } from '../scripts/check-connection.mjs';

// Synthetic data only: these tests never contact a real provider.
const NOW = Date.parse('2026-09-22T18:00:00Z'); // Tuesday, market open
const AV_KEY = 'av-SECRET-key-1';
const CG_KEY = 'cg-SECRET-key-2';
const isAv = (u) => u.hostname === 'av.test';
const markets = (u) => u.pathname.endsWith('/coins/markets');
const chart = (u) => u.pathname.includes('/market_chart');

const cfg = (env = {}) => loadConfig({ env: {
  ALPHA_VANTAGE_API_KEY: AV_KEY, COINGECKO_DEMO_API_KEY: CG_KEY,
  ALPHA_VANTAGE_BASE_URL: 'https://av.test/query', COINGECKO_BASE_URL: 'https://cg.test/api/v3', ...env,
} });

const goodRoutes = () => [
  [isAv, () => ({ body: avDaily('AAPL', '2026-09-21', 100) })],
  [markets, () => ({ body: cgMarkets([['bitcoin', 'btc', 'Bitcoin', 60000, 600]], '2026-09-22T17:57:00Z') })],
  [chart, () => ({ body: cgChart(NOW, 90) })],
];

async function run(routes, config = cfg(), cache = new MarketCache({ now: () => NOW })) {
  const f = fakeFetch(routes);
  const report = await runConnectionCheck({ config, fetchImpl: f.impl, now: () => NOW, cache });
  return { report, calls: f.calls, cache };
}

test('passes on well-formed answers and reports source, data time and delay', async () => {
  const { report, calls, cache } = await run(goodRoutes());
  assert.equal(report.overall, 'passed');
  const [av, cg] = report.providers;
  assert.equal(av.sample.price, 199);
  assert.equal(av.sample.lastDate, '2026-09-21');
  assert.match(av.delayLabel, /סוף יום/);
  assert.ok(av.assumptions.every((a) => a.result === 'confirmed'), JSON.stringify(av.assumptions));
  assert.equal(cg.sample.price, 60000);
  assert.equal(cg.sample.ageMinutes, 3);
  assert.equal(cg.sample.candles, false);
  assert.ok(cg.assumptions.every((a) => a.result === 'confirmed'), JSON.stringify(cg.assumptions));
  assert.equal(calls.length, 3, '1 Alpha Vantage + 2 CoinGecko requests');
  assert.ok(cache.peek('av:daily:AAPL'), 'warms the app cache');
  assert.equal(cache.meta.usage.alpha_vantage.dayCount, 1, 'counts against the app quota');
  const text = formatReport(report);
  for (const part of ['מקור', 'מועד הנתון', 'השהיה', 'Powered by CoinGecko']) assert.ok(text.includes(part), part);
});

test('a format that differs from the assumptions fails the check and says what differed', async () => {
  const body = avDaily('AAPL', '2026-09-21', 100);
  body['Meta Data']['5. Time Zone'] = 'UTC';
  const { report } = await run([[isAv, () => ({ body })], ...goodRoutes().slice(1)]);
  const av = report.providers[0];
  assert.equal(av.status, 'failed');
  const tz = av.assumptions.find((a) => a.id === 'av.tz');
  assert.equal(tz.result, 'contradicted');
  assert.match(tz.note, /UTC/);
  assert.equal(report.overall, 'failed');
});

test('missing CoinGecko field is reported as contradicted', async () => {
  const bad = cgMarkets([['bitcoin', 'btc', 'Bitcoin', 60000, 600]], '2026-09-22T17:57:00Z');
  delete bad[0].total_volume;
  const { report } = await run([goodRoutes()[0], [markets, () => ({ body: bad })], goodRoutes()[2]]);
  const a = report.providers[1].assumptions.find((x) => x.id === 'cg.markets');
  assert.equal(a.result, 'contradicted');
  assert.match(a.note, /total_volume/);
});

test('no keys: setup required, no requests', async () => {
  const { report, calls } = await run(goodRoutes(), cfg({ ALPHA_VANTAGE_API_KEY: '', COINGECKO_DEMO_API_KEY: '' }));
  assert.equal(report.overall, 'setup_required');
  assert.equal(calls.length, 0);
  assert.ok(report.providers.every((p) => p.assumptions.every((a) => a.result === 'not_checked')));
});

test('one key only: partial', async () => {
  const { report } = await run(goodRoutes(), cfg({ COINGECKO_DEMO_API_KEY: '' }));
  assert.equal(report.overall, 'partial');
  assert.equal(report.providers[0].status, 'passed');
});

test('a proxy block is a network failure and leaves the format unverified', async () => {
  const block = () => ({ status: 403, headers: { 'content-type': 'text/plain' }, body: 'Host not in allowlist' });
  const { report } = await run([[isAv, block], [markets, block], [chart, block]]);
  assert.equal(report.overall, 'failed');
  for (const p of report.providers) {
    assert.equal(p.error.code, 'network');
    assert.ok(p.assumptions.every((a) => a.result === 'not_checked'));
    assert.equal(p.sample, null, 'no data is shown on failure');
  }
});

test('keys never appear in the report, even when a provider echoes them', async () => {
  const echo = () => ({ body: { Information: `the parameter apikey=${AV_KEY} is invalid or missing` } });
  const cgEcho = () => ({ status: 401, body: { status: { error_code: 10002, error_message: `bad key ${CG_KEY}` } } });
  const { report } = await run([[isAv, echo], [markets, cgEcho]]);
  const text = JSON.stringify(report) + formatReport(report);
  assert.ok(!text.includes(AV_KEY) && !text.includes(CG_KEY));
  assert.equal(report.providers[0].error.code, 'auth_failed');
  assert.equal(report.providers[1].error.code, 'auth_failed');
});

test('quota already used up: no request is sent', async () => {
  const cache = new MarketCache({ now: () => NOW });
  cache.meta.usage = { alpha_vantage: { day: '2026-09-22', dayCount: 25, month: '2026-09', monthCount: 25, blockedUntil: 0 } };
  const { report, calls } = await run(goodRoutes(), cfg(), cache);
  assert.equal(report.providers[0].error.code, 'rate_limited');
  assert.ok(!calls.some((c) => isAv(c.url)));
});

test('redact and overall status helpers', () => {
  assert.equal(redact('x?apikey=abc123&y=1', []), 'x?apikey=***&y=1');
  assert.equal(redact('"x-cg-demo-api-key": "zzz999"', []), '"x-cg-demo-api-key": "***"');
  assert.equal(redact('header x-cg-demo-api-key accepted', []), 'header x-cg-demo-api-key accepted');
  assert.equal(overallStatus([{ status: 'passed' }, { status: 'setup_required' }]), 'partial');
  assert.equal(overallStatus([{ status: 'passed' }, { status: 'failed' }]), 'failed');
});
