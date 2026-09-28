/**
 * Shared cue sheet. Every visual hit and its matching sound effect read from
 * here, so moving a cue keeps picture and sound in sync.
 * All values are ABSOLUTE frames on the 1800-frame master timeline.
 */
import {ACTS} from './constants';

const I = ACTS.intro.from;
const R = ACTS.reveal.from;
const C = ACTS.chaos.from;
const X = ACTS.climax.from;

export const CUES = {
  // ── ACT I: cyber-underworld ──────────────────────────────
  introGlitches: [I + 58, I + 92, I + 151, I + 163, I + 206, I + 248, I + 262, I + 274, I + 286],
  introKingFlashes: [I + 250, I + 264, I + 278],
  introWhipOut: I + 292,

  // ── ACT II: the reveal ───────────────────────────────────
  revealGlitches: [R + 138, R + 152, R + 161, R + 167, R + 171, R + 174],
  revealHeartbeatStart: R + 110,
  revealSplitStart: R + 180, // mask begins to split away from the face
  revealSplitHold: R + 225, // the "key-art" half/half moment
  revealMaskLift: R + 262, // mask lifts off completely → flash-bang + braam
  revealNameIn: R + 380,
  revealWhipOut: R + 440,

  // ── ACT III: chaos ───────────────────────────────────────
  chaosShots: [C + 0, C + 75, C + 150, C + 225, C + 285, C + 345], // establishing shots
  chaosFlashBang: C + 75,
  chaosExplosions: [C + 165, C + 180, C + 300],
  chaosMontageStart: C + 400,
  chaosMontageEnd: C + 640,
  chaosSilenceStart: C + 640, // everything drops out: "UNTIL NOW."
  chaosRiserStart: C + 690,
  chaosWhiteOut: C + 745,

  // ── ACT IV: climax ───────────────────────────────────────
  titleSlam: X + 8,
  keyArtBuild: X + 60,
  hebrewTitleSlam: X + 96,
  endScreen: X + 190, // key-art poster hold (letterbox lifts)
  endCard: X + 258, // billing block
  finalStinger: X + 282,
} as const;

/** Local frame of an absolute cue inside an act. */
export const local = (absFrame: number, actFrom: number) => absFrame - actFrom;

/**
 * The accelerating rapid-cut montage (00:38.3 – 00:46.3). Cuts get shorter
 * and shorter; the final cut absorbs whatever frames remain.
 */
const MONTAGE_PATTERN = [24, 22, 20, 18, 16, 14, 12, 12, 10, 10, 8, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 6];

export type MontageCut = {from: number; durationInFrames: number; index: number};

export const montageCuts = (): MontageCut[] => {
  const total = CUES.chaosMontageEnd - CUES.chaosMontageStart;
  const cuts: MontageCut[] = [];
  let cursor = 0;
  MONTAGE_PATTERN.forEach((len, index) => {
    if (cursor >= total) return;
    const isLast = index === MONTAGE_PATTERN.length - 1;
    const durationInFrames = isLast ? total - cursor : Math.min(len, total - cursor);
    cuts.push({from: CUES.chaosMontageStart + cursor, durationInFrames, index});
    cursor += durationInFrames;
  });
  return cuts;
};
