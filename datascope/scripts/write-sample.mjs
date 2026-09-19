/**
 * Writes sample/datascope_sample.csv from the demo generator, so the file in the
 * repository and the one the app offers for download are the same bytes.
 *
 * Run it after changing the generator: node scripts/write-sample.mjs
 */

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { generateDemoCsv } from '../src/lib/demo.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const target = path.join(root, 'sample', 'datascope_sample.csv');

const csv = generateDemoCsv();
await mkdir(path.dirname(target), { recursive: true });
await writeFile(target, csv, 'utf8');

const rows = csv.trim().split('\n').length - 1;
console.log(`נכתב ${path.relative(root, target)} — ${rows} שורות, ${Buffer.byteLength(csv)} בייטים`);
