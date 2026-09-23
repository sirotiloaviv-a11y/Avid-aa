// Production build: syntax-checks every module, verifies that every relative
// import resolves, scans for anything that looks like a credential, then
// copies src/ to dist/. There are no third-party dependencies to bundle.
import { cp, readdir, readFile, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(root, 'src');
const dist = join(root, 'dist');

async function walk(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await walk(full));
    else out.push(full);
  }
  return out;
}

const SECRET_PATTERNS = [
  /api[_-]?key\s*[:=]\s*['"][^'"]{8,}/i,
  /secret\s*[:=]\s*['"][^'"]{8,}/i,
  /bearer\s+[a-z0-9._-]{20,}/i,
  /sk-[a-z0-9]{20,}/i,
];

const errors = [];
const files = await walk(src);
for (const file of [join(root, 'server.mjs'), ...(await walk(join(root, 'server')))].filter((f) => f.endsWith('.mjs'))) {
  try {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
  } catch (err) {
    errors.push(`${relative(root, file)}: syntax error\n${err.stderr}`);
  }
}
for (const file of files.filter((f) => f.endsWith('.js'))) {
  const rel = relative(root, file);
  try {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
  } catch (err) {
    errors.push(`${rel}: syntax error\n${err.stderr}`);
  }
  const text = await readFile(file, 'utf8');
  for (const m of text.matchAll(/(?:import|export)\s[^'"]*?from\s+['"](\.[^'"]+)['"]/g)) {
    if (!existsSync(resolve(dirname(file), m[1]))) errors.push(`${rel}: missing import ${m[1]}`);
  }
}
for (const file of files) {
  const text = await readFile(file, 'utf8');
  if (SECRET_PATTERNS.some((p) => p.test(text))) errors.push(`${relative(root, file)}: looks like it contains a credential`);
}
const html = await readFile(join(src, 'index.html'), 'utf8');
for (const m of html.matchAll(/(?:src|href)="([^":#]+)"/g)) {
  if (!existsSync(join(src, m[1]))) errors.push(`src/index.html: missing asset ${m[1]}`);
}

if (errors.length) {
  console.error(`Build failed:\n- ${errors.join('\n- ')}`);
  process.exit(1);
}
await rm(dist, { recursive: true, force: true });
await cp(src, dist, { recursive: true });
console.log(`Build OK: ${files.length} files checked and copied to dist/`);
