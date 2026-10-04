import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../src/app.js';
import { SecurityBrain } from '../src/brain.js';
import { createConnectors } from '../src/connectors/index.js';
import { DEMO_CONNECTIONS } from '../src/config.js';

let server;
let base;
let brain;

before(async () => {
  brain = await new SecurityBrain({ connectors: createConnectors(), demoConnections: DEMO_CONNECTIONS, remediationDelayMs: 5 }).init();
  const app = createApp(brain, { logger: { error() {} } });
  await new Promise((resolve) => {
    server = app.listen(0, '127.0.0.1', resolve);
  });
  base = `http://127.0.0.1:${server.address().port}/api`;
});

after(() => {
  brain.close();
  server.close();
});

const call = async (method, path, body) => {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  });
  return { status: response.status, headers: response.headers, body: await response.json() };
};

test('GET /health', async () => {
  const { status, body, headers } = await call('GET', '/health');
  assert.equal(status, 200);
  assert.equal(body.status, 'ok');
  assert.equal(headers.get('x-content-type-options'), 'nosniff');
  assert.equal(headers.get('x-powered-by'), null);
});

test('GET /dashboard returns score, integrations and recommendations', async () => {
  const { status, body } = await call('GET', '/dashboard');
  assert.equal(status, 200);
  assert.ok(Number.isInteger(body.risk.score));
  assert.equal(body.integrations.length, 6);
  assert.equal(body.recommendations.length, body.risk.open);
});

test('GET /risk-score', async () => {
  const { status, body } = await call('GET', '/risk-score');
  assert.equal(status, 200);
  assert.ok(body.score >= 0 && body.score <= 100);
  assert.ok(body.counts.critical >= 1);
  assert.ok(Array.isArray(body.trend.points));
});

test('GET /recommendations validates limit', async () => {
  assert.equal((await call('GET', '/recommendations?limit=3')).body.recommendations.length, 3);
  assert.equal((await call('GET', '/recommendations?limit=0')).status, 400);
  assert.equal((await call('GET', '/recommendations?limit=abc')).status, 400);
});

test('GET /findings supports filters', async () => {
  const { body } = await call('GET', '/findings?provider=github&severity=critical');
  assert.ok(body.total > 0);
  assert.ok(body.findings.every((f) => f.provider === 'github' && f.severity === 'critical'));
  assert.equal((await call('GET', '/findings?severity=nope')).status, 400);
  assert.equal((await call('GET', '/findings?provider=nope')).status, 404);
});

test('POST /findings/:id/remediate resolves the finding', async () => {
  const { body: list } = await call('GET', '/findings?status=open&severity=critical');
  const id = list.findings[0].id;
  const started = await call('POST', `/findings/${id}/remediate`);
  assert.equal(started.status, 202);
  assert.equal(started.body.status, 'remediating');
  assert.equal((await call('POST', `/findings/${id}/remediate`)).status, 409);
  await brain.settle();
  assert.equal((await call('GET', `/findings/${id}`)).body.status, 'resolved');
  assert.equal((await call('POST', '/findings/fnd_nope/remediate')).status, 404);
});

test('integration lifecycle: connect, pause, resume, sync, disconnect', async () => {
  const bad = await call('POST', '/integrations/microsoft-365/connect', { credentials: { tenantId: 'x' } });
  assert.equal(bad.status, 400);
  assert.ok(bad.body.fields.tenantId);

  const connected = await call('POST', '/integrations/microsoft-365/connect', {
    credentials: { tenantId: '6f1c2a9e-3b4d-4e8f-9a1b-2c3d4e5f6a7b', tenantDomain: 'acme.onmicrosoft.com' },
  });
  assert.equal(connected.status, 200);
  assert.equal(connected.body.connected, true);
  assert.equal(connected.body.account.label, 'acme.onmicrosoft.com');

  assert.equal((await call('PATCH', '/integrations/microsoft-365', { enabled: false })).body.status, 'paused');
  assert.equal((await call('PATCH', '/integrations/microsoft-365', { enabled: 'no' })).status, 400);
  assert.equal((await call('PATCH', '/integrations/microsoft-365', { enabled: true })).body.status, 'connected');

  const synced = await call('POST', '/integrations/microsoft-365/sync');
  assert.equal(synced.status, 200);
  assert.equal(synced.body.scans, 2);

  const gone = await call('POST', '/integrations/microsoft-365/disconnect');
  assert.equal(gone.body.connected, false);
  assert.equal((await call('POST', '/integrations/microsoft-365/sync')).status, 409);
});

test('POST /sync rescans every monitored integration', async () => {
  const { status, body } = await call('POST', '/sync');
  assert.equal(status, 200);
  assert.equal(body.integrations.length, 6);
});

test('error handling: unknown routes, malformed JSON, unknown integration', async () => {
  assert.equal((await call('GET', '/nope')).status, 404);
  assert.equal((await call('GET', '/integrations/okta')).status, 404);
  const malformed = await call('POST', '/integrations/aws/connect', '{"credentials":');
  assert.equal(malformed.status, 400);
  assert.match(malformed.body.error, /JSON/);
});

test('POST /demo/reset restores the seeded state', async () => {
  const { status, body } = await call('POST', '/demo/reset');
  assert.equal(status, 200);
  assert.equal(body.integrations.filter((i) => i.connected).length, 4);
});
