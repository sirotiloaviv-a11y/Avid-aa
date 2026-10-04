import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../src/app.js';
import { SecurityBrain } from '../src/brain.js';
import { createConnectors } from '../src/connectors/index.js';
import { DEMO_CONNECTIONS } from '../src/config.js';
import { createAIService } from '../src/services/aiService.js';
import { AutoFixEngine } from '../src/services/autoFix.js';

const quiet = { error() {}, warn() {} };
const makeBrain = () => new SecurityBrain({ connectors: createConnectors(), demoConnections: DEMO_CONNECTIONS, remediationDelayMs: 1 }).init();
const fixable = (brain, filter = {}) => brain.listFindings({ status: 'open', ...filter }).find((f) => f.autoFix.supported);
const manualOnly = (brain) => brain.listFindings({ status: 'open' }).find((f) => !f.autoFix.supported);

// ----------------------------------------------------------- engine level

test('runs validate → snapshot → execute → verify → rescore and resolves the finding', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 0, logger: quiet });
  const finding = fixable(brain, { severity: 'critical' });
  const before = brain.riskScore().score;

  const started = engine.start(finding.id);
  assert.equal(started.status, 'running');
  assert.equal(started.scoreBefore, before);
  assert.equal(brain.getFinding(finding.id).status, 'remediating');

  await engine.settle(started.id);
  const job = engine.get(started.id);
  assert.equal(job.status, 'succeeded');
  assert.deepEqual(job.steps.map((s) => s.key), ['validate', 'snapshot', 'execute', 'verify', 'rescore']);
  assert.ok(job.steps.every((s) => s.status === 'done' && s.detail && s.startedAt && s.finishedAt));
  assert.match(job.steps[0].detail, /just-in-time grant/);
  assert.match(job.steps[2].detail, /→ OK/);
  assert.ok(job.scoreAfter > job.scoreBefore, `${job.scoreBefore} -> ${job.scoreAfter}`);
  assert.equal(job.scoreAfter, brain.riskScore().score);
  assert.match(job.steps[4].detail, new RegExp(`${job.scoreBefore} → ${job.scoreAfter}`));

  const resolved = brain.getFinding(finding.id);
  assert.equal(resolved.status, 'resolved');
  assert.equal(resolved.resolution, 'auto-fixed');
  assert.equal(resolved.autoFixJobId, undefined, 'internal claim id is not exposed');
});

test('progress is observable while the job runs', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 15, logger: quiet });
  const job = engine.start(fixable(brain).id);
  await new Promise((r) => setTimeout(r, 25));
  const midway = engine.get(job.id);
  assert.equal(midway.status, 'running');
  assert.equal(midway.steps[0].status, 'done');
  assert.ok(midway.steps.some((s) => s.status === 'running'));
  assert.ok(midway.steps.some((s) => s.status === 'pending'));
  await engine.settle(job.id);
  assert.equal(engine.get(job.id).status, 'succeeded');
});

test('rejects manual-only findings with 422 and explains why', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 0, logger: quiet });
  const finding = manualOnly(brain);
  assert.throws(() => engine.start(finding.id), (error) => {
    assert.equal(error.status, 422);
    assert.match(error.message, /Auto-Fix is not available/);
    return true;
  });
  assert.equal(brain.getFinding(finding.id).status, 'open');
});

test('rejects unknown, duplicate, resolved and paused-integration requests', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 5, logger: quiet });
  assert.throws(() => engine.start('fnd_missing'), { status: 404 });
  assert.throws(() => engine.start(''), { status: 400 });
  assert.throws(() => engine.start(undefined), { status: 400 });

  const finding = fixable(brain);
  const job = engine.start(finding.id);
  assert.throws(() => engine.start(finding.id), { status: 409 });
  assert.throws(() => brain.remediate(finding.id), { status: 409 }, 'manual remediation is blocked during auto-fix');
  await engine.settle(job.id);
  assert.throws(() => engine.start(finding.id), { status: 409 });

  const github = fixable(brain, { provider: 'github' });
  brain.setEnabled('github', false);
  assert.throws(() => engine.start(github.id), { status: 409 });
  assert.throws(() => engine.get('fix_nope'), { status: 404 });
});

test('pausing the integration mid-flight fails the job and releases the finding', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 15, logger: quiet });
  const finding = fixable(brain, { provider: 'aws' });
  const before = brain.riskScore().score;
  const job = engine.start(finding.id);
  await new Promise((r) => setTimeout(r, 5));
  brain.setEnabled('aws', false);
  await engine.settle(job.id);

  const failed = engine.get(job.id);
  assert.equal(failed.status, 'failed');
  assert.match(failed.error, /paused/);
  assert.ok(failed.steps.some((s) => s.status === 'failed'));
  assert.ok(failed.steps.some((s) => s.status === 'skipped'));
  assert.equal(failed.scoreAfter, null);

  brain.setEnabled('aws', true);
  assert.equal(brain.getFinding(finding.id).status, 'open', 'finding released back to open');
  assert.equal(brain.riskScore().score, before);
});

test('a reset during the fix cannot resolve a finding in the fresh state', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 15, logger: quiet });
  const finding = fixable(brain);
  const job = engine.start(finding.id);
  await brain.reset();
  await engine.settle(job.id);
  assert.equal(engine.get(job.id).status, 'failed');
  assert.equal(brain.getFinding(finding.id).status, 'open');
});

test('a rescan during the fix keeps the claim', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 10, logger: quiet });
  const finding = fixable(brain, { provider: 'aws' });
  const job = engine.start(finding.id);
  await brain.sync('aws');
  await engine.settle(job.id);
  assert.equal(engine.get(job.id).status, 'succeeded');
  assert.equal(brain.getFinding(finding.id).status, 'resolved');
});

test('auto-fixing everything fixable never crashes and only raises the score', async () => {
  const brain = await makeBrain();
  const engine = new AutoFixEngine({ brain, stepMs: 0, logger: quiet });
  let previous = brain.riskScore().score;
  for (const finding of brain.listFindings({ status: 'open' }).filter((f) => f.autoFix.supported)) {
    const job = engine.start(finding.id);
    await engine.settle(job.id);
    const done = engine.get(job.id);
    assert.equal(done.status, 'succeeded', finding.templateKey);
    assert.ok(done.scoreAfter >= previous);
    previous = done.scoreAfter;
  }
  assert.ok(brain.listFindings({ status: 'open' }).every((f) => !f.autoFix.supported));
});

// -------------------------------------------------------------- HTTP API

let server;
let base;
let brain;
let engine;

before(async () => {
  brain = await makeBrain();
  engine = new AutoFixEngine({ brain, stepMs: 0, logger: quiet });
  const app = createApp(brain, { logger: quiet, autoFix: engine, ai: createAIService({ env: {}, logger: quiet }) });
  await new Promise((resolve) => { server = app.listen(0, '127.0.0.1', resolve); });
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
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: response.status, headers: response.headers, body: await response.json() };
};

test('POST /remediate/auto-fix starts a job; GET /remediate/jobs/:id reports it', async () => {
  const { body: dashboard } = await call('GET', '/dashboard');
  const rec = dashboard.recommendations.find((r) => r.autoFix.supported);
  assert.ok(rec.autoFix.permission, 'recommendations carry auto-fix capability');

  const started = await call('POST', '/remediate/auto-fix', { findingId: rec.findingId });
  assert.equal(started.status, 202);
  assert.equal(started.headers.get('location'), `/api/remediate/jobs/${started.body.id}`);
  assert.equal(started.body.findingId, rec.findingId);
  assert.equal(started.body.steps.length, 5);

  await engine.settle(started.body.id);
  const job = await call('GET', `/remediate/jobs/${started.body.id}`);
  assert.equal(job.status, 200);
  assert.equal(job.body.status, 'succeeded');
  assert.ok(job.body.scoreAfter > job.body.scoreBefore);

  const risk = await call('GET', '/risk-score');
  assert.equal(risk.body.score, job.body.scoreAfter);
  assert.equal((await call('GET', `/findings/${rec.findingId}`)).body.status, 'resolved');
});

test('auto-fix API error codes', async () => {
  assert.equal((await call('POST', '/remediate/auto-fix', {})).status, 400);
  assert.equal((await call('POST', '/remediate/auto-fix', { findingId: 42 })).status, 400);
  assert.equal((await call('POST', '/remediate/auto-fix', { findingId: 'fnd_nope' })).status, 404);
  const manual = brain.listFindings({ status: 'open' }).find((f) => !f.autoFix.supported);
  const rejected = await call('POST', '/remediate/auto-fix', { findingId: manual.id });
  assert.equal(rejected.status, 422);
  assert.match(rejected.body.error, /Auto-Fix is not available/);
  assert.equal((await call('GET', '/remediate/jobs/fix_nope')).status, 404);
});

test('GET /findings/:id/insight returns the three insight sections', async () => {
  const finding = brain.listFindings({ status: 'open' })[0];
  const { status, body } = await call('GET', `/findings/${finding.id}/insight`);
  assert.equal(status, 200);
  assert.equal(body.source, 'rules');
  assert.ok(body.executiveSummary && body.businessImpact);
  assert.ok(body.scripts.length && body.sideEffects.length);
  assert.equal((await call('GET', '/findings/fnd_nope/insight')).status, 404);
  const ai = await call('GET', '/ai/status');
  assert.equal(ai.body.provider, 'rules');
});
