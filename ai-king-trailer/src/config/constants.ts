export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const TOTAL_FRAMES = 1800; // 60 seconds

/** Seconds → frames. */
export const sec = (s: number) => Math.round(s * FPS);

/** The four acts of the trailer, in absolute frames. */
export const ACTS = {
  intro: {from: 0, durationInFrames: sec(10)}, //   00:00 – 00:10
  reveal: {from: sec(10), durationInFrames: sec(15)}, // 00:10 – 00:25
  chaos: {from: sec(25), durationInFrames: sec(25)}, //  00:25 – 00:50
  climax: {from: sec(50), durationInFrames: sec(10)}, // 00:50 – 01:00
} as const;

export type ActName = keyof typeof ACTS;

export const COLORS = {
  black: '#000000',
  navy: '#050A1C',
  midnight: '#0B1638',
  royal: '#132a6b',
  gold: '#E8C36A',
  goldLight: '#FFF1C1',
  goldDeep: '#9C6B1E',
  silver: '#E6E9EF',
  neonCyan: '#00F0FF',
  neonMagenta: '#FF2BD6',
  neonViolet: '#7B2CFF',
  alarmRed: '#FF1E2D',
  swatBlue: '#1E6BFF',
  fire: '#FF7A1A',
} as const;

/** Show a small "PLACEHOLDER · <slot>" tag over every media slot that has no footage yet. */
export const SHOW_PLACEHOLDER_TAGS = true;
