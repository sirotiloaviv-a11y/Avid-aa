import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createConnectors, PROVIDER_DEFINITIONS } from '../src/connectors/index.js';
import { SEVERITIES } from '../src/engine/risk.js';

const connectors = createConnectors();
const exampleCredentials = (connector) =>
  Object.fromEntries(connector.definition.credentialFields.map((f) => [f.name, f.example]));

test('registers the six supported providers', () => {
  assert.deepEqual([...connectors.keys()].sort(), ['aws', 'azure', 'github', 'google-workspace', 'microsoft-365', 'slack']);
  assert.equal(PROVIDER_DEFINITIONS.length, 6);
});

for (const connector of connectors.values()) {
  test(`${connector.id}: example credentials validate and produce well-formed findings`, async () => {
    const account = await connector.authenticate(exampleCredentials(connector));
    assert.ok(account.key, 'account has a key');
    assert.ok(account.label, 'account has a label');

    const findings = await connector.collect(account);
    assert.ok(findings.length >= 4, `expected at least 4 findings, got ${findings.length}`);
    const ids = new Set();
    for (const f of findings) {
      assert.ok(!ids.has(f.id), `duplicate finding id ${f.id}`);
      ids.add(f.id);
      assert.equal(f.provider, connector.id);
      assert.ok(SEVERITIES.includes(f.severity), `bad severity ${f.severity}`);
      assert.match(f.title, /\S/);
      assert.ok(f.explanation.length > 60, 'explanation is human-readable prose');
      assert.ok(!f.explanation.includes('undefined'), `explanation leaks undefined: ${f.explanation}`);
      assert.ok(!f.title.includes('undefined'), `title leaks undefined: ${f.title}`);
      assert.ok(Array.isArray(f.remediation) && f.remediation.length > 0);
      assert.ok(!Number.isNaN(Date.parse(f.detectedAt)));
      assert.equal(f.status, 'open');
    }
  });

  test(`${connector.id}: describe() exposes field patterns as strings, no functions`, () => {
    const described = connector.describe();
    assert.doesNotThrow(() => JSON.parse(JSON.stringify(described)));
    for (const field of described.credentialFields) {
      if (field.pattern) assert.equal(typeof field.pattern, 'string');
    }
    assert.equal(described.templates, undefined);
  });
}

test('the same account always yields the same findings (stable ids across restarts)', async () => {
  const github = connectors.get('github');
  const account = await github.authenticate({ organization: 'acme-corp' });
  const now = Date.parse('2026-10-01T00:00:00Z');
  const first = await github.collect(account, { now });
  const second = await github.collect(account, { now });
  assert.deepEqual(first, second);
});

test('different accounts yield different resources', async () => {
  const aws = connectors.get('aws');
  const a = await aws.collect(await aws.authenticate({ roleArn: 'arn:aws:iam::111111111111:role/Audit' }));
  const b = await aws.collect(await aws.authenticate({ roleArn: 'arn:aws:iam::222222222222:role/Audit' }));
  assert.notDeepEqual(a.map((f) => f.id), b.map((f) => f.id));
});

test('the requested signature findings are simulated', async () => {
  const titles = async (id) => {
    const c = connectors.get(id);
    return (await c.collect(await c.authenticate(exampleCredentials(c)))).map((f) => f.templateKey);
  };
  assert.ok((await titles('github')).includes('exposed-secret'));
  assert.ok((await titles('aws')).includes('s3-public-bucket'));
  assert.ok((await titles('google-workspace')).includes('unverified-external-admin'));
  assert.ok((await titles('slack')).includes('public-file-links'));
});

test('invalid credentials are rejected with per-field errors', async () => {
  const aws = connectors.get('aws');
  await assert.rejects(aws.authenticate({ roleArn: 'not-an-arn' }), (error) => {
    assert.equal(error.status, 400);
    assert.ok(error.fields.roleArn);
    return true;
  });
  const m365 = connectors.get('microsoft-365');
  const result = m365.validateCredentials({});
  assert.equal(result.ok, false);
  assert.deepEqual(Object.keys(result.errors).sort(), ['tenantDomain', 'tenantId']);
});

test('optional fields may be left empty', () => {
  const aws = connectors.get('aws');
  const result = aws.validateCredentials({ roleArn: 'arn:aws:iam::123456789012:role/VeyraAudit' });
  assert.equal(result.ok, true);
});
