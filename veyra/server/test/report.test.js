import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { inflateSync } from 'node:zlib';
import { createApp } from '../src/app.js';
import { SecurityBrain } from '../src/brain.js';
import { createConnectors } from '../src/connectors/index.js';
import { DEMO_CONNECTIONS } from '../src/config.js';
import { computeCompliance, controlsFor, FRAMEWORKS } from '../src/engine/compliance.js';
import { encodeWinAnsi, PdfDocument } from '../src/lib/pdf.js';
import { createAIService } from '../src/services/aiService.js';
import { executiveSummaryText, renderExecutiveReport, reportFilename } from '../src/services/reportPdf.js';

const quiet = { error() {}, warn() {} };
const makeBrain = () => new SecurityBrain({ connectors: createConnectors(), demoConnections: DEMO_CONNECTIONS, remediationDelayMs: 1 }).init();

/** Structural PDF checks plus the decoded text of every content stream. */
function inspectPdf(buffer) {
  const raw = buffer.toString('latin1');
  assert.ok(raw.startsWith('%PDF-1.4'), 'header');
  assert.ok(raw.trimEnd().endsWith('%%EOF'), 'trailer');

  const startxref = Number(raw.match(/startxref\s+(\d+)\s+%%EOF\s*$/)[1]);
  assert.equal(raw.slice(startxref, startxref + 4), 'xref', 'startxref points at the xref table');
  const [, first, count] = raw.slice(startxref).match(/^xref\s+(\d+) (\d+)/);
  const entries = raw.slice(startxref).split('\n').slice(2, 2 + Number(count));
  entries.slice(1).forEach((entry, i) => {
    const offset = Number(entry.slice(0, 10));
    assert.equal(raw.slice(offset, offset + `${i + 1 + Number(first)} 0 obj`.length), `${i + 1} 0 obj`, `xref offset of object ${i + 1}`);
  });

  const pages = Number(raw.match(/\/Type \/Pages .*?\/Count (\d+)/)[1]);
  const streams = [];
  const re = /\/Length (\d+) \/Filter \/FlateDecode >>\nstream\n/g;
  let match;
  while ((match = re.exec(raw))) {
    const start = match.index + match[0].length;
    const length = Number(match[1]);
    assert.equal(raw.slice(start + length, start + length + 10), '\nendstream', 'stream length is exact');
    streams.push(inflateSync(buffer.subarray(start, start + length)).toString('latin1'));
  }
  // Text from Tj operators, unescaped.
  const text = streams.join('\n').match(/\((?:\\.|[^\\)])*\) Tj/g)?.map((t) => t.slice(1, -4)
    .replace(/\\([()\\])/g, '$1')
    .replace(/\\(\d{3})/g, (_, o) => String.fromCharCode(parseInt(o, 8)))).join('\n') ?? '';
  return { pages, streams, text };
}

// -------------------------------------------------------------- PDF writer

test('PdfDocument writes a structurally valid multi-page PDF', () => {
  const doc = new PdfDocument({ info: { Title: 'Test (1)' } });
  doc.text('Hello (world) \\ back', 40, 40, { size: 12 });
  doc.rect(40, 80, 100, 40, { fill: '#ff0000', radius: 8 });
  doc.arc(200, 200, 50, -135, 90, { color: '#00ff00', width: 8 });
  doc.addPage();
  doc.text('Second page – “quoted” · 43 → 46', 40, 40);
  const { pages, streams, text } = inspectPdf(doc.toBuffer());
  assert.equal(pages, 2);
  assert.equal(streams.length, 2);
  assert.match(text, /Hello \(world\) \\ back/);
  assert.match(streams[0], / h f Q/, 'rounded rect is a filled closed path');
  assert.match(streams[0], / c /, 'arcs are bezier curves');
});

test('WinAnsi encoding maps typography and transliterates the rest', () => {
  assert.deepEqual(encodeWinAnsi('–—•…'), [0x96, 0x97, 0x95, 0x85]);
  assert.deepEqual(encodeWinAnsi('é'), [0xe9]);
  assert.equal(String.fromCharCode(...encodeWinAnsi('43 → 46 ≥ 5')), '43 -> 46 >= 5');
  assert.equal(String.fromCharCode(...encodeWinAnsi('漢')), '?');
  assert.deepEqual(encodeWinAnsi(undefined), []);
});

test('text measurement and wrapping respect the width', () => {
  const doc = new PdfDocument();
  assert.equal(doc.measure('iiii', 10), 4 * 2.22);
  assert.ok(doc.measure('bold', 10, 'bold') > doc.measure('bold', 10));
  const lines = doc.wrap('The quick brown fox jumps over the lazy dog '.repeat(4), 150, 10);
  assert.ok(lines.length > 3);
  assert.ok(lines.every((line) => doc.measure(line, 10) <= 150));
  const broken = doc.wrap('x'.repeat(200), 50, 10);
  assert.ok(broken.every((line) => doc.measure(line, 10) <= 50), 'long words are broken');
});

// ------------------------------------------------------------- compliance

test('controlsFor combines category mapping and explicit references', () => {
  const soc2 = FRAMEWORKS.find((f) => f.id === 'soc2');
  assert.deepEqual(controlsFor(soc2, { category: 'Network', frameworks: ['SOC 2 CC6.6', 'CIS AWS 5.2'] }), ['CC6.6']);
  assert.ok(controlsFor(soc2, { category: 'Logging', frameworks: ['SOC 2 CC7.3'] }).includes('CC7.3'));
  assert.deepEqual(controlsFor(soc2, { category: 'Unknown', frameworks: ['SOC 2 ZZ9.9'] }), []);
});

test('readiness: blocking findings count 0, minor 0.5, passing 1', () => {
  const checks = [
    { provider: 'p', key: 'a', category: 'Network', frameworks: [] },
    { provider: 'p', key: 'b', category: 'Network', frameworks: [] },
  ];
  const soc2 = (open) => computeCompliance(checks, open).find((f) => f.id === 'soc2');
  assert.equal(soc2([]).readiness, 100);
  assert.equal(soc2([{ provider: 'p', templateKey: 'a', severity: 'high' }]).readiness, 50);
  assert.equal(soc2([{ provider: 'p', templateKey: 'a', severity: 'low' }]).readiness, 75);
  const failing = soc2([{ provider: 'p', templateKey: 'a', severity: 'critical' }, { provider: 'p', templateKey: 'b', severity: 'low' }]);
  assert.equal(failing.readiness, 25);
  assert.equal(failing.failing, 1);
  assert.equal(failing.topGaps[0].id, 'CC6.6');
  assert.equal(computeCompliance([], []).find((f) => f.id === 'soc2').readiness, null);
});

test('demo tenant compliance is in range and improves with remediation', async () => {
  const brain = await makeBrain();
  const before = brain.compliance();
  for (const fw of before) {
    assert.ok(fw.readiness > 0 && fw.readiness < 100, `${fw.name} ${fw.readiness}`);
    assert.equal(fw.passing + fw.partial + fw.failing, fw.assessed);
  }
  for (const rec of brain.recommendations({ limit: 10 })) brain.remediate(rec.findingId);
  await brain.settle();
  const after = brain.compliance();
  for (const fw of after) {
    assert.ok(fw.readiness > before.find((b) => b.id === fw.id).readiness, fw.name);
  }
});

// ------------------------------------------------------------------ report

test('executive report model has every required section', async () => {
  const brain = await makeBrain();
  const report = brain.executiveReport();
  assert.equal(report.tenant, 'Acme Corp');
  assert.match(report.risk.grade, /^[A-F]$/);
  assert.deepEqual(report.integrations.map((i) => i.id).sort(), ['aws', 'azure', 'github', 'google-workspace', 'microsoft-365', 'slack']);
  assert.equal(report.topActions.length, 5);
  assert.equal(report.topActions[0].severity, 'critical');
  assert.ok(report.projectedScore > report.risk.score);
  assert.deepEqual(report.compliance.map((f) => f.name), ['SOC 2', 'ISO 27001']);
  const summary = executiveSummaryText(report);
  assert.match(summary, /rated F \(Critical\)/);
  assert.match(summary, /SOC 2/);
});

test('rendered PDF contains summary, grade, all platforms, top 5 and compliance', async () => {
  const brain = await makeBrain();
  const report = brain.executiveReport();
  const { pages, text } = inspectPdf(renderExecutiveReport(report));
  assert.ok(pages >= 2 && pages <= 4, `pages: ${pages}`);
  assert.match(text, /Executive Security Summary/);
  assert.match(text, new RegExp(`GRADE ${report.risk.grade}`));
  for (const name of ['Google Workspace', 'Microsoft 365', 'Amazon Web Services', 'Microsoft Azure', 'GitHub', 'Slack']) {
    assert.ok(text.includes(name), name);
  }
  assert.match(text, /Top 5 Items Requiring CISO Action/);
  for (const item of report.topActions) assert.ok(text.includes(item.title.slice(0, 30)), item.title);
  assert.match(text, /Compliance Posture/);
  for (const fw of report.compliance) assert.ok(text.includes(`${fw.readiness}%`), fw.name);
  assert.match(text, /Page 1 of \d/);
});

test('report renders for edge cases: nothing connected, everything fixed', async () => {
  const brain = await makeBrain();
  for (const id of Object.keys(DEMO_CONNECTIONS)) brain.disconnect(id);
  const empty = inspectPdf(renderExecutiveReport(brain.executiveReport()));
  assert.match(empty.text, /No open findings/);
  assert.match(empty.text, /n\/a/);

  const clean = await makeBrain();
  for (const f of clean.listFindings({ status: 'open' })) clean.remediate(f.id);
  await clean.settle();
  const report = clean.executiveReport();
  assert.equal(report.risk.score, 100);
  const { text } = inspectPdf(renderExecutiveReport(report));
  assert.match(text, /GRADE A/);
  assert.equal(reportFilename(report), `veyra-executive-report-${report.generatedAt.slice(0, 10)}.pdf`);
});

// -------------------------------------------------------------- HTTP API

let server;
let base;
let apiBrain;

before(async () => {
  apiBrain = await makeBrain();
  const app = createApp(apiBrain, { logger: quiet, ai: createAIService({ env: {}, logger: quiet }) });
  await new Promise((resolve) => { server = app.listen(0, '127.0.0.1', resolve); });
  base = `http://127.0.0.1:${server.address().port}/api`;
});

after(() => {
  apiBrain.close();
  server.close();
});

test('GET /reports/pdf downloads the PDF', async () => {
  const response = await fetch(`${base}/reports/pdf`);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/pdf');
  assert.match(response.headers.get('content-disposition'), /^attachment; filename="veyra-executive-report-\d{4}-\d{2}-\d{2}\.pdf"$/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  const buffer = Buffer.from(await response.arrayBuffer());
  assert.equal(Number(response.headers.get('content-length')), buffer.length);
  assert.match(inspectPdf(buffer).text, /Executive Security Report/);
});

test('GET /reports/executive and /compliance return JSON', async () => {
  const report = await (await fetch(`${base}/reports/executive`)).json();
  assert.equal(report.topActions.length, 5);
  const { frameworks } = await (await fetch(`${base}/compliance`)).json();
  assert.equal(frameworks.length, 2);
  assert.ok(frameworks[0].controls.length > 0);
  const dashboard = await (await fetch(`${base}/dashboard`)).json();
  assert.equal(dashboard.compliance.length, 2);
  assert.equal(dashboard.compliance[0].controls, undefined, 'dashboard carries the summary only');
});
