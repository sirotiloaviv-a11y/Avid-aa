import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeRiskScore, findingPenalty, gradeFor, projectedGain, scoreFromPenalty } from '../src/engine/risk.js';
import { buildRecommendations, priorityOf } from '../src/engine/prioritize.js';

let seq = 0;
const finding = (overrides = {}) => ({
  id: `f${++seq}`,
  provider: 'aws',
  title: 'Something',
  severity: 'medium',
  category: 'Network',
  exposure: 'internal',
  exploitability: 1,
  resource: { name: 'r', type: 't' },
  explanation: 'x',
  remediation: ['y'],
  detectedAt: '2026-09-20T00:00:00.000Z',
  status: 'open',
  ...overrides,
});

const integrations = [{ id: 'aws', name: 'AWS' }, { id: 'github', name: 'GitHub' }];

test('no findings means a perfect score', () => {
  const risk = computeRiskScore([], integrations, 6);
  assert.equal(risk.score, 100);
  assert.equal(risk.grade, 'A');
  assert.deepEqual(risk.counts, { critical: 0, high: 0, medium: 0, low: 0 });
  assert.deepEqual(risk.coverage, { monitored: 2, total: 6, percent: 33 });
});

test('score stays within 0-100 and decreases monotonically with penalty', () => {
  let previous = 101;
  for (let penalty = 0; penalty <= 5000; penalty += 50) {
    const score = scoreFromPenalty(penalty);
    assert.ok(score >= 0 && score <= 100);
    assert.ok(score <= previous);
    previous = score;
  }
});

test('public exposure weighs more than internal', () => {
  assert.ok(findingPenalty(finding({ exposure: 'public' })) > findingPenalty(finding({ exposure: 'internal' })));
  assert.ok(findingPenalty(finding({ severity: 'critical' })) > findingPenalty(finding({ severity: 'high' })));
});

test('critical findings lower the score more than medium ones', () => {
  const critical = computeRiskScore([finding({ severity: 'critical' })], integrations, 6);
  const medium = computeRiskScore([finding({ severity: 'medium' })], integrations, 6);
  assert.ok(critical.score < medium.score);
});

test('breakdowns cover each monitored integration and category', () => {
  const risk = computeRiskScore(
    [finding({ provider: 'aws', category: 'Network' }), finding({ provider: 'github', category: 'Secrets', severity: 'critical' })],
    integrations, 6,
  );
  assert.deepEqual(risk.byIntegration.map((i) => i.id), ['aws', 'github']);
  assert.equal(risk.byCategory[0].category, 'Secrets');
  assert.equal(risk.byCategory.reduce((sum, c) => sum + c.open, 0), 2);
});

test('grades map to score bands', () => {
  assert.equal(gradeFor(95).grade, 'A');
  assert.equal(gradeFor(85).grade, 'B');
  assert.equal(gradeFor(72).grade, 'C');
  assert.equal(gradeFor(60).grade, 'D');
  assert.equal(gradeFor(10).grade, 'F');
});

test('projected gain is positive and larger for worse findings', () => {
  const crit = finding({ severity: 'critical', exposure: 'public' });
  const low = finding({ severity: 'low' });
  const open = [crit, low, finding(), finding({ severity: 'high' })];
  assert.ok(projectedGain(crit, open) > projectedGain(low, open));
  assert.ok(projectedGain(crit, open) > 0);
});

test('recommendations rank by severity first, then priority', () => {
  const now = Date.parse('2026-10-01T00:00:00Z');
  const open = [
    finding({ severity: 'medium', exposure: 'public', exploitability: 2 }),
    finding({ severity: 'critical', exposure: 'internal' }),
    finding({ severity: 'high', exposure: 'internal' }),
    finding({ severity: 'high', exposure: 'public' }),
  ];
  const recs = buildRecommendations(open, new Map([['aws', { id: 'aws', name: 'AWS', shortName: 'AWS', color: '#f90' }]]), { now });
  assert.deepEqual(recs.map((r) => r.severity), ['critical', 'high', 'high', 'medium']);
  assert.equal(recs[1].exposure, 'public');
  assert.deepEqual(recs.map((r) => r.rank), [1, 2, 3, 4]);
  assert.equal(recs[0].integration.name, 'AWS');
});

test('older issues get a higher priority', () => {
  const now = Date.parse('2026-10-01T00:00:00Z');
  const fresh = finding({ detectedAt: '2026-09-30T00:00:00Z' });
  const stale = finding({ detectedAt: '2026-08-01T00:00:00Z' });
  assert.ok(priorityOf(stale, now) > priorityOf(fresh, now));
});

test('limit trims the recommendation list', () => {
  const open = Array.from({ length: 12 }, () => finding());
  assert.equal(buildRecommendations(open, new Map(), { limit: 5 }).length, 5);
});
