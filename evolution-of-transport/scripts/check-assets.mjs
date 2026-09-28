// Pre-render gate: every clip must exist and fit its slot. Keyframes and
// audio are reported but optional. Run with `npm run check`.
import {execFileSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';

const root = new URL('..', import.meta.url).pathname;
const manifest = JSON.parse(await readFile(join(root, 'shots/manifest.json'), 'utf8'));
const pub = (p) => join(root, 'public', p);
const MIN_RATE = 0.75;
const MAX_RATE = 1.33;

const remotionBin = join(root, 'node_modules/.bin/remotion');
const probe = (file) => {
	if (!existsSync(remotionBin)) return null;
	try {
		const out = execFileSync(
			remotionBin,
			['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
				'stream=width,height,r_frame_rate:format=duration', '-of', 'json', file],
			{encoding: 'utf8'},
		);
		const j = JSON.parse(out);
		const s = j.streams[0];
		const [n, d] = s.r_frame_rate.split('/').map(Number);
		return {width: s.width, height: s.height, fps: n / d, duration: Number(j.format.duration)};
	} catch {
		return null;
	}
};

const errors = [];
const warnings = [];

for (const shot of manifest.shots) {
	const clip = pub(`clips/${shot.clip}`);
	if (!existsSync(clip)) {
		errors.push(`${shot.id}: missing public/clips/${shot.clip}`);
	} else {
		const info = probe(clip);
		if (info) {
			if (Math.abs(info.duration - shot.sourceSec) > 0.15) {
				errors.push(`${shot.id}: clip is ${info.duration.toFixed(2)}s but manifest sourceSec is ${shot.sourceSec}; update sourceSec`);
			}
			if (info.width / info.height > 0.6) {
				errors.push(`${shot.id}: clip is ${info.width}x${info.height}; generate it vertical 9:16`);
			} else if (info.height < 1920) {
				warnings.push(`${shot.id}: clip is ${info.width}x${info.height}; upscale to 1080x1920 for best quality`);
			}
			if (Math.abs(info.fps - manifest.fps) > 0.5) {
				warnings.push(`${shot.id}: clip is ${info.fps.toFixed(2)}fps; the edit is ${manifest.fps}fps`);
			}
		}
		const slot = shot.endSec - shot.startSec;
		const rate = (shot.sourceSec - shot.trimStartFrames / manifest.fps) / slot;
		if (rate < MIN_RATE || rate > MAX_RATE) {
			errors.push(`${shot.id}: retime ${rate.toFixed(2)}x is outside ${MIN_RATE}-${MAX_RATE}x; regenerate at ~${slot}s`);
		}
	}
}

const keyframes = new Set(manifest.shots.flatMap((s) => [s.startKeyframe, s.endKeyframe]));
for (const k of keyframes) {
	if (!existsSync(pub(`keyframes/${k}`))) warnings.push(`keyframe public/keyframes/${k} not saved (keep it for re-generation)`);
}

const audio = [manifest.music.file, ...manifest.sfx.map((c) => c.file)];
const missingAudio = audio.filter((f) => !existsSync(pub(f)));

for (const w of warnings) console.warn(`warn  ${w}`);
if (missingAudio.length) {
	console.warn(`info  ${audio.length - missingAudio.length}/${audio.length} audio files present; missing ones are skipped:`);
	for (const f of missingAudio) console.warn(`        public/${f}`);
}
if (errors.length) {
	for (const e of errors) console.error(`error ${e}`);
	console.error(`\n${errors.length} problem(s); not rendering.`);
	process.exit(1);
}
console.log('All clips present and within spec.');
