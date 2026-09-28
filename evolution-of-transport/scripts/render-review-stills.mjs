// Exports review stills to out/review/: the middle of every shot and the
// frames either side of every cut (where a bad match cut shows up).
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';

const root = new URL('..', import.meta.url).pathname;
const manifest = JSON.parse(await readFile(join(root, 'shots/manifest.json'), 'utf8'));
const fps = manifest.fps;

const frames = new Map();
manifest.shots.forEach((s, i) => {
	const start = Math.round(s.startSec * fps);
	const end = Math.round(s.endSec * fps);
	frames.set(Math.round((start + end) / 2), `${s.id}-mid`);
	if (i > 0) {
		frames.set(start - 2, `cut${i}-before`);
		frames.set(start, `cut${i}-at`);
		frames.set(start + 2, `cut${i}-after`);
	}
});

const outDir = join(root, 'out/review');
await mkdir(outDir, {recursive: true});
const serveUrl = await bundle({entryPoint: join(root, 'src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'Evolution'});

for (const [frame, label] of [...frames].sort((a, b) => a[0] - b[0])) {
	const output = join(outDir, `${String(frame).padStart(3, '0')}-${label}.jpg`);
	await renderStill({serveUrl, composition, frame, output, imageFormat: 'jpeg', jpegQuality: 90});
	console.log(output);
}
