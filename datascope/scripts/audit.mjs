/**
 * Source audit: the privacy and security promises the README makes, checked
 * mechanically instead of by reading the diff.
 *
 * It fails the build (and one of the tests) when a source file:
 *   - references an external origin from HTML, CSS or an import,
 *   - reaches the network at runtime (fetch / XHR / beacon / WebSocket),
 *   - persists imported data (localStorage / sessionStorage / IndexedDB / cookies),
 *   - assigns HTML from a string (innerHTML and friends), which is how imported
 *     CSV text would turn into markup,
 *   - or evaluates code from a string.
 *
 * Comments and string literals are handled separately: identifiers are searched
 * in code with comments stripped, so a docblock may discuss `localStorage`
 * without tripping the check, while `'http://www.w3.org/2000/svg'` inside a
 * string stays intact for the URL check.
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';

/** Namespace and spec URLs that are identifiers, not network requests. */
const ALLOWED_URL_PREFIXES = ['http://www.w3.org/'];

const FORBIDDEN_IDENTIFIERS = [
  { pattern: /\bfetch\s*\(/, label: 'fetch(' },
  { pattern: /\bXMLHttpRequest\b/, label: 'XMLHttpRequest' },
  { pattern: /\bWebSocket\b/, label: 'WebSocket' },
  { pattern: /\bEventSource\b/, label: 'EventSource' },
  { pattern: /sendBeacon\s*\(/, label: 'navigator.sendBeacon(' },
  { pattern: /\blocalStorage\b/, label: 'localStorage' },
  { pattern: /\bsessionStorage\b/, label: 'sessionStorage' },
  { pattern: /\bindexedDB\b/i, label: 'indexedDB' },
  { pattern: /document\s*\.\s*cookie/, label: 'document.cookie' },
  { pattern: /\.innerHTML\b/, label: '.innerHTML' },
  { pattern: /\.outerHTML\b/, label: '.outerHTML' },
  { pattern: /insertAdjacentHTML\b/, label: 'insertAdjacentHTML' },
  { pattern: /\beval\s*\(/, label: 'eval(' },
  { pattern: /new\s+Function\s*\(/, label: 'new Function(' },
];

/**
 * Removes line and block comments while respecting string and template literals.
 * Good enough for this codebase (no regex literal here contains a comment
 * opener); it is a lint helper, not a JavaScript parser.
 * @param {string} source
 * @returns {string}
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

function isExternal(url) {
  const value = url.trim();
  if (value === '') return false;
  if (value.startsWith('//')) return true;
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) {
    if (value.startsWith('data:')) return false;
    if (value.startsWith('blob:')) return false;
    if (ALLOWED_URL_PREFIXES.some((prefix) => value.startsWith(prefix))) return false;
    return true;
  }
  return false;
}

/**
 * @param {string} root Project root.
 * @param {string[]} files Paths relative to root.
 * @returns {Promise<string[]>} Findings, empty when everything passes.
 */
export async function auditSources(root, files) {
  /** @type {string[]} */
  const findings = [];

  for (const relative of files) {
    const source = await readFile(path.join(root, relative), 'utf8');
    const extension = path.extname(relative);

    if (extension === '.html') {
      for (const match of source.matchAll(/\b(?:src|href)\s*=\s*"([^"]*)"/g)) {
        if (isExternal(match[1])) {
          findings.push(`${relative}: external reference ${match[1]}`);
        }
      }
      for (const match of source.matchAll(/<script\b[^>]*>/g)) {
        if (/\bintegrity=|\bcrossorigin=/.test(match[0])) {
          findings.push(`${relative}: script tag looks remote: ${match[0]}`);
        }
      }
      continue;
    }

    if (extension === '.css') {
      // Comments are stripped first: a comment may name @import while explaining
      // that the stylesheet does not use one.
      const css = source.replace(/\/\*[\s\S]*?\*\//g, ' ');
      for (const match of css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) {
        if (isExternal(match[1])) findings.push(`${relative}: external url() ${match[1]}`);
      }
      if (/@import/.test(css)) findings.push(`${relative}: @import is not allowed`);
      continue;
    }

    const code = stripComments(source);
    for (const { pattern, label } of FORBIDDEN_IDENTIFIERS) {
      if (pattern.test(code)) findings.push(`${relative}: uses ${label}`);
    }
    for (const match of code.matchAll(/(?:^|[^\w])(?:import|from)\s*\(?\s*['"]([^'"]+)['"]/g)) {
      if (isExternal(match[1])) findings.push(`${relative}: imports external module ${match[1]}`);
    }
  }

  return findings;
}

/** The files the audit covers: everything that ships to the browser. */
export const SHIPPED_FILES = Object.freeze([
  'index.html',
  'src/styles.css',
  'src/main.js',
  'src/lib/csv.js',
  'src/lib/validate.js',
  'src/lib/stats.js',
  'src/lib/selection.js',
  'src/lib/format.js',
  'src/lib/summary.js',
  'src/lib/exporters.js',
  'src/lib/demo.js',
  'src/ui/dom.js',
  'src/ui/charts.js',
  'src/ui/table.js',
  'src/ui/panels.js',
]);
