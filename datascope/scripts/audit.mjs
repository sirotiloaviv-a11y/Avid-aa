/**
 * Source audit: the properties the README promises, checked mechanically.
 *
 * This app talks to the network - that is its whole purpose - so the audit is
 * not "no requests" any more. It is "only these hosts, and nothing else":
 *
 *   - every absolute URL in shipped code points at a market data provider on
 *     the allowlist, or at the app's own origin,
 *   - no analytics or error-reporting service is contacted,
 *   - no HTML is assigned from a string (imported names and symbols come from
 *     third parties and must never become markup),
 *   - no code is evaluated from a string,
 *   - the page loads no external script, stylesheet or font.
 *
 * Comments and string literals are treated separately: identifiers are matched
 * against code with comments stripped, so a docblock may discuss `innerHTML`
 * without tripping the check, while `'https://api.binance.com'` inside a string
 * is still seen by the URL check.
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';

/** Hosts the app is allowed to contact at runtime. */
export const ALLOWED_HOSTS = Object.freeze([
  'api.binance.com',
  'stream.binance.com',
  'data-stream.binance.vision',
  'api.binance.us',
  'stream.binance.us',
  'api.coingecko.com',
  'finnhub.io',
  'ws.finnhub.io',
  'query1.finance.yahoo.com',
  'localhost',
  '127.0.0.1',
]);

/** URLs that are identifiers or documentation, not network destinations. */
const URL_EXEMPT_PREFIXES = ['http://www.w3.org/', 'https://finnhub.io/docs', 'data:', 'blob:'];

const FORBIDDEN_IDENTIFIERS = [
  { pattern: /\.innerHTML\b/, label: '.innerHTML' },
  { pattern: /\.outerHTML\b/, label: '.outerHTML' },
  { pattern: /insertAdjacentHTML\b/, label: 'insertAdjacentHTML' },
  { pattern: /document\s*\.\s*write\b/, label: 'document.write' },
  { pattern: /\beval\s*\(/, label: 'eval(' },
  { pattern: /new\s+Function\s*\(/, label: 'new Function(' },
  { pattern: /sendBeacon\s*\(/, label: 'navigator.sendBeacon(' },
  { pattern: /\bgtag\b|googletagmanager|\bmixpanel\b|\bsentry\b|\bhotjar\b/i, label: 'analytics or error reporting' },
];

/** The CSV *reader* is gone; this makes its return a build failure. */
const FORBIDDEN_IMPORTS = [
  { pattern: /from\s+['"][^'"]*\/csv\.js['"]/, label: 'CSV import module' },
  { pattern: /\bparseCsv\s*\(/, label: 'parseCsv(' },
  { pattern: /\bFileReader\b/, label: 'FileReader' },
  { pattern: /type\s*=\s*['"]file['"]/, label: 'file input' },
];

/**
 * Removes line and block comments while respecting string and template literals.
 * Good enough for this codebase (no regex literal here contains a comment
 * opener); it is a lint helper, not a JavaScript parser.
 * @param {string} source
 */
export function stripComments(source) {
  let out = '';
  let quote = null;
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];

    if (quote) {
      out += ch;
      if (ch === '\\') {
        out += next ?? '';
        i += 1;
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }

    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
      out += ch;
      continue;
    }
    if (ch === '/' && next === '/') {
      while (i < source.length && source[i] !== '\n') i += 1;
      out += '\n';
      continue;
    }
    if (ch === '/' && next === '*') {
      i += 2;
      while (i < source.length && !(source[i] === '*' && source[i + 1] === '/')) i += 1;
      i += 1;
      out += ' ';
      continue;
    }
    out += ch;
  }
  return out;
}

/**
 * @param {string} url
 * @param {string[]} allowedHosts
 * @returns {boolean} True when the destination is not permitted.
 */
export function isDisallowedUrl(url, allowedHosts = ALLOWED_HOSTS) {
  const value = url.trim();
  if (value === '') return false;
  if (URL_EXEMPT_PREFIXES.some((prefix) => value.startsWith(prefix))) return false;
  if (value.startsWith('//')) return true;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(value)) return false; // relative: same origin

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return true;
  }
  if (!['https:', 'wss:', 'http:', 'ws:'].includes(parsed.protocol)) return true;
  return !allowedHosts.includes(parsed.hostname);
}

/**
 * @param {string} root
 * @param {string[]} files Paths relative to root.
 * @param {{allowedHosts?: string[]}} [options]
 * @returns {Promise<string[]>} Findings, empty when everything passes.
 */
export async function auditSources(root, files, options = {}) {
  const allowedHosts = options.allowedHosts ?? ALLOWED_HOSTS;
  /** @type {string[]} */
  const findings = [];

  for (const relative of files) {
    const source = await readFile(path.join(root, relative), 'utf8');
    const extension = path.extname(relative);

    if (extension === '.html') {
      const markup = source.replace(/<!--[\s\S]*?-->/g, ' ');
      for (const match of markup.matchAll(/\b(?:src|href)\s*=\s*"([^"]*)"/g)) {
        if (isDisallowedUrl(match[1], allowedHosts)) {
          findings.push(`${relative}: external reference ${match[1]}`);
        }
      }
      // The page itself must stay self-contained even though the app calls APIs.
      for (const match of markup.matchAll(/<(script|link)\b[^>]*>/g)) {
        if (/\bintegrity=|\bcrossorigin=/.test(match[0])) {
          findings.push(`${relative}: remote asset tag: ${match[0].slice(0, 80)}`);
        }
      }
      for (const { pattern, label } of FORBIDDEN_IMPORTS) {
        if (pattern.test(markup)) findings.push(`${relative}: contains ${label}`);
      }
      continue;
    }

    if (extension === '.css') {
      const css = source.replace(/\/\*[\s\S]*?\*\//g, ' ');
      for (const match of css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) {
        if (isDisallowedUrl(match[1], allowedHosts)) {
          findings.push(`${relative}: external url() ${match[1]}`);
        }
      }
      if (/@import/.test(css)) findings.push(`${relative}: @import is not allowed`);
      continue;
    }

    const code = stripComments(source);

    for (const { pattern, label } of FORBIDDEN_IDENTIFIERS) {
      if (pattern.test(code)) findings.push(`${relative}: uses ${label}`);
    }
    for (const { pattern, label } of FORBIDDEN_IMPORTS) {
      if (pattern.test(code)) findings.push(`${relative}: contains ${label}`);
    }
    // Every absolute URL that survives comment stripping is a real destination.
    for (const match of code.matchAll(/['"`](([a-z][a-z0-9+.-]*:)?\/\/[^'"`\s]+)['"`]/gi)) {
      if (isDisallowedUrl(match[1], allowedHosts)) {
        findings.push(`${relative}: contacts non-allowlisted host ${match[1]}`);
      }
    }
  }

  return findings;
}

/** The files the audit covers: everything that ships to the browser. */
export const SHIPPED_FILES = Object.freeze([
  'index.html',
  'src/styles.css',
  'src/main.js',
  'src/lib/model.js',
  'src/lib/format.js',
  'src/lib/series.js',
  'src/lib/alerts.js',
  'src/lib/assets.js',
  'src/lib/market.js',
  'src/lib/config.js',
  'src/lib/storage.js',
  'src/lib/exporters.js',
  'src/providers/binance.js',
  'src/providers/finnhub.js',
  'src/providers/yahoo.js',
  'src/providers/coingecko.js',
  'src/providers/connection.js',
  'src/ui/dom.js',
  'src/ui/charts.js',
  'src/ui/dashboard.js',
  'src/ui/ticker.js',
  'src/ui/alerts-ui.js',
  'src/ui/notifications.js',
]);
