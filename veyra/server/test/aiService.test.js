import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildRuleInsight, buildUserPrompt, createAIService, INSIGHT_SCHEMA, normalizeModelInsight, SYSTEM_PROMPT,
} from '../src/services/aiService.js';
import { SecurityBrain } from '../src/brain.js';
import { createConnectors } from '../src/connectors/index.js';
import { DEMO_CONNECTIONS } from '../src/config.js';
import { getPlaybook, PLAYBOOK_KEYS } from '../src/remediation/playbooks.js';

const quiet = { error() {}, warn() {} };
const brain = await new SecurityBrain({ connectors: createConnectors(), demoConnections: DEMO_CONNECTIONS }).init();
const contextFor = (templateKey) => {
  const finding = brain.listFindings().find((f) => f.templateKey === templateKey);
  return brain.findingContext(finding.id);
};
const s3 = contextFor('s3-public-bucket');

const VALID_OUTPUT = {
  executive_summary: 'A storage bucket holding customer exports is open to the internet. Anyone can download it today.',
  business_impact: 'A reportable breach under GDPR with notification duties and likely contractual penalties.',
  remediation_scripts: [{ label: 'AWS CLI', language: 'bash', code: 'aws s3api put-public-access-block --bucket b ...' }],
  side_effects: ['Anonymous website assets served from the bucket will return 403.'],
};

function fakeAnthropic(respond) {
  const calls = [];
  return {
    calls,
    client: { beta: { messages: { create: async (params) => { calls.push(params); return respond(params); } } } },
  };
}
const claudeReply = (payload, extra = {}) => ({
  model: 'claude-opus-5-5',
  stop_reason: 'end_turn',
  content: [{ type: 'text', text: typeof payload === 'string' ? payload : JSON.stringify(payload) }],
  ...extra,
});

// ------------------------------------------------------------ rule engine

test('every finding template has a playbook', () => {
  const keys = [...createConnectors().values()].flatMap((c) => c.templates.map((t) => t.key));
  assert.deepEqual(keys.filter((k) => !PLAYBOOK_KEYS.includes(k)), []);
});

test('rule-based insights cover all three sections for every seeded finding', () => {
  for (const finding of brain.listFindings()) {
    const context = brain.findingContext(finding.id);
    const insight = buildRuleInsight(context);
    assert.equal(insight.source, 'rules');
    assert.match(insight.executiveSummary, /risk in /, finding.templateKey);
    assert.ok(insight.businessImpact.length > 80, finding.templateKey);
    assert.ok(insight.scripts.length >= 1 && insight.scripts.every((s) => s.code.trim()), finding.templateKey);
    assert.ok(insight.sideEffects.length >= 1, finding.templateKey);
    const text = JSON.stringify(insight);
    assert.ok(!/undefined|NaN|\[object Object\]/.test(text), `${finding.templateKey}: ${text.slice(0, 200)}`);
  }
});

test('rule insight scripts are tailored to the resource', () => {
  const insight = buildRuleInsight(s3);
  assert.ok(insight.scripts.some((s) => s.code.includes(s3.finding.resource.name)));
  assert.ok(insight.scripts.some((s) => s.language === 'hcl'), 'includes a Terraform variant');
  assert.match(insight.executiveSummary, new RegExp(`${s3.score} → ${s3.score + s3.projectedGain}`));
});

test('playbook values from finding data are shell-sanitized', () => {
  const finding = { ...s3.finding, resource: { ...s3.finding.resource, name: 'bucket; rm -rf / $(whoami)' } };
  const code = getPlaybook(finding, s3.account).scripts.map((s) => s.code).join('\n');
  assert.ok(!code.includes('rm -rf /'), code);
  assert.ok(!code.includes('$(whoami)'), code);
});

// --------------------------------------------------------- provider choice

test('no API key: uses the rules engine and says why', async () => {
  const ai = createAIService({ env: {}, logger: quiet });
  const status = await ai.status();
  assert.equal(status.provider, 'rules');
  assert.equal(status.live, false);
  assert.match(status.reason, /No ANTHROPIC_API_KEY or OPENAI_API_KEY/);
  const insight = await ai.insight(s3);
  assert.equal(insight.source, 'rules');
  assert.equal(insight.fallbackReason, undefined);
  assert.equal(insight.findingId, s3.finding.id);
  assert.equal(insight.autoFix.supported, true);
});

test('key set but SDK not installed: falls back to rules with a reason', async () => {
  const ai = createAIService({
    env: { ANTHROPIC_API_KEY: 'sk-test' },
    loadModule: async () => { throw new Error('Cannot find package'); },
    logger: quiet,
  });
  const status = await ai.status();
  assert.equal(status.provider, 'rules');
  assert.match(status.reason, /@anthropic-ai\/sdk is not installed/);
  assert.equal((await ai.insight(s3)).source, 'rules');
});

test('VEYRA_AI_PROVIDER=rules forces the rules engine even with a key', async () => {
  const fake = fakeAnthropic(() => claudeReply(VALID_OUTPUT));
  const ai = createAIService({ env: { VEYRA_AI_PROVIDER: 'rules', ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, logger: quiet });
  assert.equal((await ai.insight(s3)).source, 'rules');
  assert.equal(fake.calls.length, 0);
});

test('SDK constructor receives the key, timeout and retry settings', async () => {
  let options;
  class FakeSdk {
    constructor(opts) {
      options = opts;
      this.beta = { messages: { create: async () => claudeReply(VALID_OUTPUT) } };
    }
  }
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'sk-test' }, loadModule: async () => ({ default: FakeSdk }), timeoutMs: 5000, logger: quiet });
  assert.equal((await ai.insight(s3)).source, 'claude');
  assert.deepEqual(options, { apiKey: 'sk-test', timeout: 5000, maxRetries: 1 });
});

// ------------------------------------------------------------------ Claude

test('Claude: request shape uses JSON-schema output, server-side fallback and untrusted-data framing', async () => {
  const fake = fakeAnthropic(() => claudeReply(VALID_OUTPUT));
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, logger: quiet });
  const insight = await ai.insight(s3);

  assert.equal(insight.source, 'claude');
  assert.equal(insight.model, 'claude-opus-5-5');
  assert.equal(insight.executiveSummary, VALID_OUTPUT.executive_summary);
  assert.deepEqual(insight.scripts, [{ label: 'AWS CLI', language: 'bash', code: VALID_OUTPUT.remediation_scripts[0].code }]);
  assert.equal(insight.autoFix.supported, true, 'auto-fix capability comes from the playbook, not the model');

  const [params] = fake.calls;
  assert.equal(params.model, 'claude-opus-5-5');
  assert.deepEqual(params.output_config.format, { type: 'json_schema', schema: INSIGHT_SCHEMA });
  assert.equal(params.output_config.effort, 'medium');
  assert.deepEqual(params.betas, ['server-side-fallback-2026-07-01']);
  assert.equal(params.fallbacks, 'default');
  assert.equal(params.system, SYSTEM_PROMPT);
  assert.match(params.system, /never follow\s+instructions/);
  assert.match(params.messages[0].content, /<finding>[\s\S]*acme-data-lake[\s\S]*<\/finding>/);
  assert.ok(!('thinking' in params), 'thinking is left at the model default');
});

test('Claude: model and effort are configurable', async () => {
  const fake = fakeAnthropic(() => claudeReply(VALID_OUTPUT));
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k', VEYRA_ANTHROPIC_MODEL: 'claude-sonnet-5-5', VEYRA_AI_EFFORT: 'low' }, clients: { anthropic: fake }, logger: quiet });
  await ai.insight(s3);
  assert.equal(fake.calls[0].model, 'claude-sonnet-5-5');
  assert.equal(fake.calls[0].output_config.effort, 'low');
});

test('Claude: results are cached per finding and status; refresh bypasses the cache', async () => {
  const fake = fakeAnthropic(() => claudeReply(VALID_OUTPUT));
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, logger: quiet });
  await ai.insight(s3);
  const second = await ai.insight(s3);
  assert.equal(second.cached, true);
  assert.equal(fake.calls.length, 1);
  await ai.insight(s3, { refresh: true });
  assert.equal(fake.calls.length, 2);
});

test('Claude: concurrent requests for one finding share a single call', async () => {
  const fake = fakeAnthropic(async () => {
    await new Promise((r) => setTimeout(r, 20));
    return claudeReply(VALID_OUTPUT);
  });
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, logger: quiet });
  const results = await Promise.all([ai.insight(s3), ai.insight(s3), ai.insight(s3)]);
  assert.equal(fake.calls.length, 1);
  assert.ok(results.every((r) => r.source === 'claude'));
});

for (const [name, reply, pattern] of [
  ['refusal', claudeReply('', { stop_reason: 'refusal', content: [] }), /declined/],
  ['truncated output', claudeReply('{"executive', { stop_reason: 'max_tokens' }), /truncated/],
  ['invalid JSON', claudeReply('not json at all'), /invalid JSON/],
  ['missing sections', claudeReply({ ...VALID_OUTPUT, remediation_scripts: [] }), /missing required sections/],
]) {
  test(`Claude: ${name} falls back to the rules engine`, async () => {
    const fake = fakeAnthropic(() => reply);
    const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, logger: quiet });
    const insight = await ai.insight(s3);
    assert.equal(insight.source, 'rules');
    assert.match(insight.fallbackReason, pattern);
    assert.ok(insight.scripts.length > 0);
    const again = await ai.insight(s3);
    assert.notEqual(again.cached, true, 'fallbacks are not cached');
  });
}

test('Claude: network errors and timeouts fall back without throwing', async () => {
  const failing = fakeAnthropic(() => { throw new Error('ECONNRESET'); });
  const ai1 = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: failing }, logger: quiet });
  assert.match((await ai1.insight(s3)).fallbackReason, /ECONNRESET/);

  const hanging = fakeAnthropic(() => new Promise(() => {}));
  const ai2 = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: hanging }, timeoutMs: 10, logger: quiet });
  const started = Date.now();
  const insight = await ai2.insight(s3);
  assert.equal(insight.source, 'rules');
  assert.match(insight.fallbackReason, /did not respond/);
  assert.ok(Date.now() - started < 5000);
});

test('Claude: an authentication error disables the provider for later calls', async () => {
  class AuthenticationError extends Error {}
  const fake = fakeAnthropic(() => { throw new AuthenticationError('invalid x-api-key'); });
  const ai = createAIService({
    env: { ANTHROPIC_API_KEY: 'bad' },
    clients: { anthropic: { client: fake.client, sdk: { AuthenticationError } } },
    logger: quiet,
  });
  assert.equal((await ai.insight(s3)).source, 'rules');
  const status = await ai.status();
  assert.equal(status.live, false);
  assert.match(status.reason, /invalid x-api-key/);
  await ai.insight(contextFor('root-no-mfa'));
  assert.equal(fake.calls.length, 1, 'no further calls after an auth failure');
});

test('Claude: repeated transient failures open a cool-down', async () => {
  let clock = 1_000_000;
  const fake = fakeAnthropic(() => { throw new Error('overloaded'); });
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'k' }, clients: { anthropic: fake }, now: () => clock, logger: quiet });
  for (const key of ['s3-public-bucket', 'root-no-mfa', 'sg-open-ssh']) await ai.insight(contextFor(key));
  assert.equal(fake.calls.length, 3);
  const cooled = await ai.insight(contextFor('cloudtrail-disabled'));
  assert.match(cooled.fallbackReason, /temporarily unavailable/);
  assert.equal(fake.calls.length, 3);
  assert.equal((await ai.status()).coolingDown, true);
  clock += 61_000;
  await ai.insight(contextFor('cloudtrail-disabled'));
  assert.equal(fake.calls.length, 4, 'retries after the cool-down');
});

// ------------------------------------------------------------------ OpenAI

test('OpenAI: used when only OPENAI_API_KEY is set, with strict JSON schema', async () => {
  const calls = [];
  const client = {
    chat: {
      completions: {
        create: async (params) => {
          calls.push(params);
          return { model: 'gpt-4o', choices: [{ finish_reason: 'stop', message: { content: JSON.stringify(VALID_OUTPUT) } }] };
        },
      },
    },
  };
  const ai = createAIService({ env: { OPENAI_API_KEY: 'k' }, clients: { openai: { client } }, logger: quiet });
  const insight = await ai.insight(s3);
  assert.equal(insight.source, 'openai');
  assert.equal((await ai.status()).provider, 'openai');
  assert.equal(calls[0].response_format.type, 'json_schema');
  assert.equal(calls[0].response_format.json_schema.strict, true);
});

test('OpenAI: a refusal falls back to the rules engine', async () => {
  const client = { chat: { completions: { create: async () => ({ choices: [{ message: { refusal: 'no' } }] }) } } };
  const ai = createAIService({ env: { OPENAI_API_KEY: 'k' }, clients: { openai: { client } }, logger: quiet });
  assert.match((await ai.insight(s3)).fallbackReason, /declined/);
});

test('Claude is preferred when both keys are set', async () => {
  const fake = fakeAnthropic(() => claudeReply(VALID_OUTPUT));
  const ai = createAIService({ env: { ANTHROPIC_API_KEY: 'a', OPENAI_API_KEY: 'o' }, clients: { anthropic: fake, openai: { client: {} } }, logger: quiet });
  assert.equal((await ai.status()).provider, 'anthropic');
});

// -------------------------------------------------------- normalization

test('model output is normalized and bounded', () => {
  const normalized = normalizeModelInsight({
    ...VALID_OUTPUT,
    remediation_scripts: [
      ...Array.from({ length: 5 }, (_, i) => ({ label: `s${i}`, language: 'cobol', code: 'x' })),
    ],
    side_effects: ['a', '', 42, 'b'],
    executive_summary: 'x'.repeat(5000),
  });
  assert.equal(normalized.scripts.length, 3);
  assert.equal(normalized.scripts[0].language, 'text');
  assert.deepEqual(normalized.sideEffects, ['a', 'b']);
  assert.ok(normalized.executiveSummary.length <= 1500);
});

test('prompt contains the finding and the reference playbook, not internal ids', () => {
  const prompt = buildUserPrompt(s3);
  assert.match(prompt, /<reference_playbook>/);
  assert.match(prompt, /put-public-access-block/);
  assert.ok(!prompt.includes(s3.finding.id));
});

test('installed SDKs construct with the options the service passes', async () => {
  for (const name of ['@anthropic-ai/sdk', 'openai']) {
    let mod;
    try {
      mod = await import(name);
    } catch {
      continue; // optional dependency not installed in this environment
    }
    const Sdk = mod.default ?? mod;
    const client = new Sdk({ apiKey: 'test-key', timeout: 1000, maxRetries: 1 });
    if (name === 'openai') assert.equal(typeof client.chat.completions.create, 'function');
    else assert.equal(typeof client.beta.messages.create, 'function');
    assert.equal(typeof Sdk.AuthenticationError, 'function');
  }
});
