import {Easing, interpolate, random} from 'remotion';

const CLAMP = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** interpolate() with clamping on both ends — what you want 95% of the time. */
export const lerp = (
  frame: number,
  input: readonly number[],
  output: readonly number[],
  easing?: (t: number) => number,
) => interpolate(frame, input as number[], output as number[], {...CLAMP, easing});

/** Fade in over `inFrames`, hold, fade out over `outFrames` (local frames). */
export const fadeInOut = (frame: number, duration: number, inFrames = 12, outFrames = 12) =>
  lerp(frame, [0, inFrames, duration - outFrames, duration], [0, 1, 1, 0]);

/**
 * Impulse envelope for a list of hit frames: jumps to 1 on each hit and
 * decays over `decay` frames. Use it for glitches, flashes, shake.
 */
export const impulse = (frame: number, hits: readonly number[], decay = 8) => {
  let v = 0;
  for (const hit of hits) {
    const d = frame - hit;
    if (d >= 0 && d < decay) v = Math.max(v, 1 - d / decay);
  }
  return v;
};

/** Deterministic camera shake: returns a CSS transform. */
export const shake = (frame: number, intensity: number, seed = 'shake') => {
  if (intensity <= 0) return 'none';
  const x = (random(`${seed}-x-${frame}`) - 0.5) * 2 * intensity * 28;
  const y = (random(`${seed}-y-${frame}`) - 0.5) * 2 * intensity * 18;
  const r = (random(`${seed}-r-${frame}`) - 0.5) * 2 * intensity * 1.2;
  return `translate(${x}px, ${y}px) rotate(${r}deg)`;
};

/** Slow, organic handheld drift (sum of sines — smooth, unlike shake()). */
export const handheld = (frame: number, amount = 1) => {
  const x = (Math.sin(frame / 37) * 6 + Math.sin(frame / 13 + 1.3) * 2) * amount;
  const y = (Math.cos(frame / 41) * 5 + Math.sin(frame / 17 + 0.4) * 2) * amount;
  const r = Math.sin(frame / 53) * 0.35 * amount;
  return `translate(${x}px, ${y}px) rotate(${r}deg)`;
};

export const EASE = {
  out: Easing.bezier(0.16, 1, 0.3, 1),
  in: Easing.bezier(0.7, 0, 0.84, 0),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  whip: Easing.bezier(0.9, 0, 0.1, 1),
};

/** Stable id usable inside SVG url(#…) references. */
export const svgId = (prefix: string, seed: string | number) =>
  `${prefix}-${String(seed).replace(/[^a-zA-Z0-9_-]/g, '')}`;
