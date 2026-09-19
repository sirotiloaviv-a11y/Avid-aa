/**
 * The privacy and security promises, as tests.
 *
 * The source audit is the mechanical half (no external references, no network,
 * no persistence, no innerHTML, no eval). The rest checks that hostile text from
 * an imported CSV stays inert everywhere it can travel: into the statistics, into
 * the summary, into the exports and into a download filename.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { auditSources, SHIPPED_FILES, stripComments } from '../scripts/audit.mjs';
import { validateDataset } from '../src/lib/validate.js';
import { computeStats } from '../src/lib/stats.js';
import { selectRows } from '../src/lib/selection.js';
import { buildSummary } from '../src/lib/summary.js';
import { buildCsv, buildTextReport, safeFileName } from '../src/lib/exporters.js';
import { parseCsv, quoteCsvCell } from '../src/lib/csv.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/* ------------------------------------------------------------------- audit */

test('no shipped file reaches the network, persists data, or writes HTML', async () => {
  const findings = await auditSources(root, [...SHIPPED_FILES]);
  assert.deepEqual(findings, []);
});

test('the audit actually catches what it claims to catch', async () => {
  // Guards against an audit that passes because its patterns are broken.
  const cases = [
    ['fetch.js', 'export const go = () => fetch("/x");', /uses fetch\(/],
    ['store.js', 'export const go = (v) => { localStorage.setItem("k", v); };', /localStorage/],
    ['html.js', 'export const go = (n, t) => { n.innerHTML = t; };', /innerHTML/],
    ['eval.js', 'export const go = (s) => eval(s);', /uses eval\(/],
    ['remote.js', 'import x from "https://cdn.example.com/x.js";', /external module/],
    ['page.html', '<script src="https://cdn.example.com/x.js"></script>', /external reference/],
    ['sheet.css', '@import url("https://fonts.example.com/x.css");', /@import/],
  ];

  const { mkdtemp, writeFile } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const scratch = await mkdtemp(path.join(tmpdir(), 'datascope-audit-'));
  for (const [name, source, expected] of cases) {
    await writeFile(path.join(scratch, name), source, 'utf8');
    const findings = await auditSources(scratch, [name]);
    assert.equal(findings.length >= 1, true, name);
    assert.match(findings.join('\n'), expected, name);
  }
});

test('the audit ignores forbidden words inside comments and namespace URLs', () => {
  const code = stripComments(`
    // this one mentions localStorage in a line comment
    /* and innerHTML in a block comment */
    const ns = 'http://www.w3.org/2000/svg';
    const path = 'a//b';
  `);
  assert.equal(code.includes('localStorage'), false);
  assert.equal(code.includes('innerHTML'), false);
  assert.equal(code.includes('http://www.w3.org/2000/svg'), true);
  assert.equal(code.includes('a//b'), true);
});

test('the DOM layer only ever sets text, never markup', async () => {
  for (const relative of SHIPPED_FILES.filter((file) => file.endsWith('.js'))) {
    const code = stripComments(await readFile(path.join(root, relative), 'utf8'));
    assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(code), false, relative);
  }
  // And the one place that creates elements uses textContent.
  const dom = await readFile(path.join(root, 'src/ui/dom.js'), 'utf8');
  assert.match(dom, /textContent/);
});

test('the page declares no external origin and no inline analytics', async () => {
  const raw = await readFile(path.join(root, 'index.html'), 'utf8');
  // Comments are removed first: they describe what the page avoids, using the
  // very words this test searches for.
  const html = raw.replace(/<!--[\s\S]*?-->/g, ' ');
  assert.equal(/https?:\/\/(?!www\.w3\.org)/.test(html), false);
  assert.equal(/gtag|analytics|googletagmanager|sentry|hotjar|telemetry/i.test(html), false);
  assert.match(raw, /כלי לימודי לניתוח נתונים היסטוריים/);
});

/* ------------------------------------------------ hostile imported content */

const HOSTILE_SYMBOLS = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '=HYPERLINK("http://evil.example","x")',
  '"><svg/onload=alert(1)>',
  'javascript:alert(1)',
  '../../etc/passwd',
  '-2+3+cmd|calc',
];

function importHostile(symbol) {
  // Quoted with the project's own CSV quoter, which is how such a value would
  // legitimately appear in a file someone exported from another tool.
  const cell = quoteCsvCell(symbol);
  const csv =
    'date,symbol,close,volume\n' +
    `2024-01-02,${cell},100,10\n` +
    `2024-01-03,${cell},110,20\n`;
  const result = validateDataset(csv, { fileName: 'hostile.csv' });
  assert.equal(result.ok, true, symbol);
  return result.dataset;
}

test('hostile symbols import as ordinary text and keep working as selectors', () => {
  for (const symbol of HOSTILE_SYMBOLS) {
    const dataset = importHostile(symbol);
    assert.deepEqual(dataset.symbols, [symbol], symbol);
    const rows = selectRows(dataset.rows, { symbol });
    assert.equal(rows.length, 2, symbol);
    assert.equal(computeStats(rows).count, 2, symbol);
  }
});

test('a hostile symbol stays inert in the CSV export and round-trips as text', () => {
  for (const symbol of HOSTILE_SYMBOLS) {
    const dataset = importHostile(symbol);
    const csv = buildCsv(dataset.rows);
    const { records } = parseCsv(csv);
    const exported = records[1].cells[1];

    // Never starts a formula.
    assert.equal(/^[=+\-@\t\r]/.test(exported), false, symbol);
    // The original text is preserved (possibly behind a leading apostrophe), so
    // nothing is silently altered or dropped.
    assert.ok(exported === symbol || exported === `'${symbol}`, symbol);
    // CSV structure survives: still exactly four columns per row.
    for (const record of records) assert.equal(record.cells.length, 4, symbol);
  }
});

test('a hostile symbol cannot shape the download filename', () => {
  for (const symbol of HOSTILE_SYMBOLS) {
    const name = safeFileName(symbol, '2026-09-19', 'csv');
    assert.match(name, /^datascope_[A-Za-z0-9._-]+_2026-09-19\.csv$/, symbol);
    assert.equal(name.includes('/'), false, symbol);
    assert.equal(name.includes('\\'), false, symbol);
    assert.equal(name.includes('..'), false, symbol);
    assert.equal(name.includes('<'), false, symbol);
  }
});

test('the report and summary carry hostile text as plain strings', () => {
  const symbol = '<img src=x onerror=alert(1)>';
  const dataset = importHostile(symbol);
  const stats = computeStats(selectRows(dataset.rows, { symbol }));
  const summary = buildSummary({
    symbol,
    fileName: 'hostile.csv',
    isDemo: false,
    requestedRange: { from: null, to: null },
    stats,
  });
  const report = buildTextReport({
    symbol,
    fileName: 'hostile.csv',
    isDemo: false,
    requestedRange: { from: null, to: null },
    stats,
    summary,
    generatedAt: '2026-09-19',
  });
  assert.equal(typeof report, 'string');
  assert.ok(report.includes(symbol));
  for (const paragraph of summary.paragraphs) assert.equal(typeof paragraph, 'string');
});

test('an oversized cell is truncated in the issue report, so a report cannot be flooded', () => {
  const huge = 'x'.repeat(5000);
  const result = validateDataset(`date,symbol,close,volume\n${huge},AAA,100,1\n`);
  assert.equal(result.ok, false);
  const issue = result.issues.find((item) => item.kind === 'invalid-date');
  assert.ok(issue.value.length < 60);
  assert.ok(issue.value.endsWith('…'));
});

test('a file name from the operating system is only ever used as text', () => {
  const result = validateDataset('date,symbol,close,volume\n2024-01-02,AAA,100,1\n', {
    fileName: '<script>alert(1)</script>.csv',
  });
  assert.equal(result.ok, true);
  assert.equal(result.dataset.fileName, '<script>alert(1)</script>.csv');
});
