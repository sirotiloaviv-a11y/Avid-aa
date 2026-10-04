import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SecurityBrain } from '../src/brain.js';
import { createConnectors } from '../src/connectors/index.js';
import { DEMO_CONNECTIONS } from '../src/config.js';

const makeBrain = async (options = {}) => {
  const brain = new SecurityBrain({
    connectors: createConnectors(),
    demoConnections: DEMO_CONNECTIONS,
    remediationDelayMs: 5,
    ...options,
  });
  return brain.init();
};

test('init connects the demo integrations and leaves the others available', async () => {
  const brain = await makeBrain();
  const byId = Object.fromEntries(brain.listIntegrations().map((i) => [i.id, i]));
  for (const id of Object.keys(DEMO_CONNECTIONS)) {
    assert.equal(byId[id].connected, true, id);
    assert.equal(byId[id].status, 'connected', id);
    assert.ok(byId[id].findings.open > 0, id);
  }
  assert.equal(byId['microsoft-365'].connected, false);
  assert.equal(byId.azure.connected, false);

  const risk = brain.riskScore();
  assert.ok(risk.score > 0 && risk.score < 100, `score ${risk.score}`);
  assert.ok(risk.counts.critical > 0);
  assert.equal(risk.coverage.monitored, 4);
  assert.equal(risk.trend.points.length, 31);
});

test('remediating a finding resolves it and raises the score', async () => {
  const brain = await makeBrain();
  const before = brain.riskScore().score;
  const [top] = brain.recommendations({ limit: 1 });
  assert.equal(top.severity, 'critical');

  const started = brain.remediate(top.findingId);
  assert.equal(started.status, 'remediating');
  assert.throws(() => brain.remediate(top.findingId), { status: 409 });

  await brain.settle();
  assert.equal(brain.getFinding(top.findingId).status, 'resolved');
  assert.equal(brain.getFinding(top.findingId).resolution, 'remediated');
  const after = brain.riskScore().score;
  assert.ok(after > before, `${after} should be greater than ${before}`);
  assert.ok(!brain.recommendations().some((r) => r.findingId === top.findingId));
  assert.throws(() => brain.remediate(top.findingId), { status: 409 });
});

test('resolved findings stay resolved after a rescan', async () => {
  const brain = await makeBrain();
  const target = brain.listFindings({ provider: 'aws', severity: 'critical' })[0];
  brain.remediate(target.id);
  await brain.settle();
  await brain.sync('aws');
  assert.equal(brain.getFinding(target.id).status, 'resolved');
});

test('connecting a new integration adds its findings and coverage', async () => {
  const brain = await makeBrain();
  const before = brain.riskScore();
  const view = await brain.connect('azure', {
    tenantId: '6f1c2a9e-3b4d-4e8f-9a1b-2c3d4e5f6a7b',
    subscriptionId: '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d',
  });
  assert.equal(view.connected, true);
  assert.ok(view.findings.open > 0);
  const after = brain.riskScore();
  assert.equal(after.coverage.monitored, before.coverage.monitored + 1);
  assert.ok(after.open > before.open);
  assert.ok(after.score < before.score);
});

test('invalid connection details are rejected and leave state untouched', async () => {
  const brain = await makeBrain();
  await assert.rejects(brain.connect('azure', { tenantId: 'nope' }), (error) => {
    assert.equal(error.status, 400);
    assert.ok(error.details.fields.tenantId);
    assert.ok(error.details.fields.subscriptionId);
    return true;
  });
  assert.equal(brain.getIntegration('azure').status, 'disconnected');
});

test('pausing monitoring removes findings from the score; resuming restores them', async () => {
  const brain = await makeBrain();
  const before = brain.riskScore();
  const paused = brain.setEnabled('github', false);
  assert.equal(paused.status, 'paused');
  const during = brain.riskScore();
  assert.ok(during.score > before.score);
  assert.equal(during.coverage.monitored, 3);
  assert.ok(!brain.recommendations().some((r) => r.integration.id === 'github'));
  assert.throws(() => brain.remediate(brain.listFindings({ provider: 'github' })[0].id), { status: 409 });

  brain.setEnabled('github', true);
  assert.equal(brain.riskScore().score, before.score);
});

test('disconnecting removes the provider findings', async () => {
  const brain = await makeBrain();
  brain.disconnect('slack');
  assert.equal(brain.listFindings({ provider: 'slack' }).length, 0);
  assert.equal(brain.getIntegration('slack').connected, false);
  assert.throws(() => brain.disconnect('slack'), { status: 409 });
  assert.throws(() => brain.setEnabled('slack', true), { status: 409 });
  await assert.rejects(brain.sync('slack'), { status: 409 });
});

test('unknown ids and bad filters produce client errors', async () => {
  const brain = await makeBrain();
  assert.throws(() => brain.getIntegration('okta'), { status: 404 });
  assert.throws(() => brain.getFinding('fnd_missing'), { status: 404 });
  assert.throws(() => brain.listFindings({ severity: 'urgent' }), { status: 400 });
  assert.throws(() => brain.setEnabled('aws', 'yes'), { status: 400 });
});

test('findings can be filtered and searched', async () => {
  const brain = await makeBrain();
  const critical = brain.listFindings({ severity: 'critical' });
  assert.ok(critical.length > 0 && critical.every((f) => f.severity === 'critical'));
  const s3 = brain.listFindings({ q: 's3 bucket' });
  assert.ok(s3.length > 0 && s3.every((f) => f.provider === 'aws'));
});

test('concurrent syncs of one integration share a single scan', async () => {
  const brain = await makeBrain();
  const before = brain.getIntegration('aws').scans;
  await Promise.all([brain.sync('aws'), brain.sync('aws'), brain.sync('aws')]);
  assert.equal(brain.getIntegration('aws').scans, before + 1);
});

test('reset restores the seeded demo state', async () => {
  const brain = await makeBrain();
  const original = brain.riskScore().score;
  brain.disconnect('aws');
  await brain.reset();
  assert.equal(brain.riskScore().score, original);
  assert.equal(brain.getIntegration('aws').connected, true);
});
