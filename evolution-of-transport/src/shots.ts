// Timing, clip files, conform settings and sound cues come from
// shots/manifest.json (shared with scripts/check-assets.mjs). Prompts for
// every shot live in shots/SHOTS.md under the same ids.
import manifest from '../shots/manifest.json';

export const FPS: number = manifest.fps;
export const WIDTH: number = manifest.width;
export const HEIGHT: number = manifest.height;

// Frames the incoming clip blends over the outgoing one at a cut. 0 = a hard
// cut on matching frames, which is the intended edit: each clip is generated
// to end on the exact keyframe the next one starts from. Raise to 2-3 only to
// hide a small grade or codec mismatch at a seam; it is not a dissolve.
export const SEAM_FRAMES: number = manifest.seamFrames;

export type ShotSpec = (typeof manifest.shots)[number];
export type Shot = ShotSpec & {
	from: number;
	duration: number;
	// Frames this clip starts early to blend over the previous one.
	seamIn: number;
	playbackRate: number;
};

// Retime range that still reads as natural motion; outside it, regenerate.
export const MIN_RATE = 0.75;
export const MAX_RATE = 1.33;

export const TIMELINE: Shot[] = manifest.shots.map((s, i) => {
	const start = Math.round(s.startSec * FPS);
	const end = Math.round(s.endSec * FPS);
	const seamIn = i === 0 ? 0 : SEAM_FRAMES;
	const from = start - seamIn;
	const duration = end - from;
	// Stretch or squeeze the usable part of the clip to fill its slot exactly.
	const usableSec = s.sourceSec - s.trimStartFrames / FPS;
	const playbackRate = usableSec / (duration / FPS);
	return {...s, from, duration, seamIn, playbackRate};
});

const last = TIMELINE[TIMELINE.length - 1];
export const TOTAL_FRAMES = last.from + last.duration; // 750 = 25s

export const MUSIC = manifest.music;
export const SFX = manifest.sfx;
