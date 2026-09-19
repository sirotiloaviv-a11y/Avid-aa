/**
 * Production build.
 *
 * There is no bundler here, and that is deliberate: the app is plain ES modules
 * that a browser loads directly, so the build's job is to check and to package,
 * not to transform. It:
 *
 *   1. imports every shipped module, which fails on a syntax error and on any
 *      module that touches the DOM at import time,
 *   2. runs the source audit (external references, network calls, persistence,
 *      innerHTML, eval),
 *   3. minifies the stylesheet (comments and whitespace only),
 *   4. copies everything into dist/ and writes dist/build-info.json with a
 *      content hash per file.
 *
 * Output is a static folder that can be served by any file server.
 */

import { createHash } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { auditSources, SHIPPED_FILES } from './audit.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const dist = path.join(root, 'dist');

/**
 * Comment and whitespace removal only. No selector rewriting, no property
 * merging: a stylesheet this size does not need the risk.
 * @param {string} css
 */
export function minifyCss(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*([{}:;,>])\s*/g, '$1')
    .replace(/;}/g, '}')
    .trim();
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex').slice(0, 16);
}

async function main() {
  const started = Date.now();
  console.log('DataScope build');
  console.log('---------------');

  // 1. Every shipped module must import cleanly in plain Node - no DOM present.
  const modules = SHIPPED_FILES.filter((file) => file.endsWith('.js'));
  for (const relative of modules) {
    await import(pathToFileURL(path.join(root, relative)).href);
  }
  console.log(`✓ ${modules.length} modules load without a DOM`);

  // 2. Audit.
  const findings = await auditSources(root, [...SHIPPED_FILES]);
  if (findings.length > 0) {
    console.error('✗ source audit failed:');
    for (const finding of findings) console.error(`   - ${finding}`);
    process.exitCode = 1;
    return;
  }
  console.log(`✓ source audit clean (${SHIPPED_FILES.length} files)`);

  // 3 + 4. Package.
  await rm(dist, { recursive: true, force: true });
  await mkdir(dist, { recursive: true });

  /** @type {Record<string, {bytes: number, hash: string}>} */
  const manifest = {};
  let totalBytes = 0;

  for (const relative of SHIPPED_FILES) {
    const source = await readFile(path.join(root, relative), 'utf8');
    const output = relative.endsWith('.css') ? minifyCss(source) : source;
    const target = path.join(dist, relative);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, output, 'utf8');
    const bytes = Buffer.byteLength(output);
    totalBytes += bytes;
    manifest[relative] = { bytes, hash: sha256(output) };
    const savedNote = relative.endsWith('.css')
      ? ` (from ${Buffer.byteLength(source)} bytes)`
      : '';
    console.log(`  ${relative.padEnd(24)} ${String(bytes).padStart(7)} bytes${savedNote}`);
  }

  await writeFile(
    path.join(dist, 'build-info.json'),
    `${JSON.stringify(
      {
        name: 'datascope',
        builtAt: new Date().toISOString(),
        fileCount: SHIPPED_FILES.length,
        totalBytes,
        files: manifest,
      },
      null,
      2,
    )}\n`,
    'utf8',
  );

  console.log('---------------');
  console.log(
    `✓ dist/ ready: ${SHIPPED_FILES.length} files, ${(totalBytes / 1024).toFixed(1)} kB, ${
      Date.now() - started
    } ms`,
  );
  console.log('  serve it with: npm run preview');
}

await main();
