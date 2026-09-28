/**
 * Every external asset the trailer uses, in one place.
 *
 * VIDEO: each slot is `null` until you generate the shot (see the AI video
 * prompt above each scene component) and drop the file in `public/video/`.
 * A `null` slot renders a procedural stand-in, so the trailer always renders.
 *
 * AUDIO: `npm install` generates placeholder WAVs into `public/audio/`.
 * Replace any of them with licensed trailer music / SFX of the same name,
 * or point the path at a new file (mp3/wav/aac all work).
 */
import {staticFile} from 'remotion';

export const IMAGES = {
  /** The golden cyber-crown + mask. */
  kingMask: staticFile('images/ai-king-mask.jpg'),
  /** The man behind the mask. For the cleanest reveal use a background-removed PNG. */
  kingFace: staticFile('images/aviv-face.png'),
  /** Finished key art / poster, used on the end screen. */
  keyArt: staticFile('images/key-art.jpg'),
};

/**
 * Face-alignment data for the mask → face reveal. Coordinates are fractions of
 * each image: (x, y) = centre of the eye line, `eyeToChin` = eye line → chin
 * distance as a fraction of image height. Tweak these if you swap the photos.
 */
export const PORTRAIT_FRAMING = {
  kingMask: {naturalWidth: 546, naturalHeight: 869, x: 0.503, y: 0.542, eyeToChin: 0.27},
  kingFace: {naturalWidth: 1206, naturalHeight: 2622, x: 0.489, y: 0.3725, eyeToChin: 0.26},
} as const;

const video = (file: string | null) => (file ? staticFile(`video/${file}`) : null);

export const VIDEOS = {
  // ACT I
  introCity: video(null), // e.g. video('intro-city.mp4')
  introSilhouette: video(null),
  // ACT II
  revealThrone: video(null),
  // ACT III
  swatBreach: video(null),
  serverRoom: video(null),
  streetExplosion: video(null),
  helicopterRooftop: video(null),
  kingWalksAway: video(null),
  carChase: video(null),
  // ACT IV
  titleBackground: video(null),
};

export type VideoSlot = keyof typeof VIDEOS;

export const AUDIO = {
  score: staticFile('audio/score.wav'),
  rain: staticFile('audio/rain.wav'),
  glitch: staticFile('audio/glitch.wav'),
  riser: staticFile('audio/riser.wav'),
  braam: staticFile('audio/braam.wav'),
  impact: staticFile('audio/impact.wav'),
  whoosh: staticFile('audio/whoosh.wav'),
  siren: staticFile('audio/siren.wav'),
  tinnitus: staticFile('audio/tinnitus.wav'),
  heartbeat: staticFile('audio/heartbeat.wav'),
  explosion: staticFile('audio/explosion.wav'),
};
