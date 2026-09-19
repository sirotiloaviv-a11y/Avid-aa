/**
 * The icon set.
 *
 * These are hand-drawn in the Lucide visual language - 24x24 box, 2px round
 * stroke, `currentColor` - because this project ships no dependencies and the
 * environment it was built in has no package registry. They are not Lucide and
 * do not claim to be; they are originals drawn to sit beside it without looking
 * out of place.
 *
 * Every icon is decorative: it appears next to text that already says the same
 * thing, and carries `aria-hidden` so a screen reader never reads a glyph in
 * place of a label.
 */

import { svg } from './dom.js';

/**
 * Path data per icon. A string is one path; an array is several strokes.
 * Rects are written as `rect:x,y,w,h,rx` so filled shapes stay readable.
 */
const PATHS = {
  'trending-up': ['M22 7 13.5 15.5l-5-5L2 17', 'M16 7h6v6'],
  'trending-down': ['M22 17 13.5 8.5l-5 5L2 7', 'M16 17h6v-6'],
  minus: 'M5 12h14',
  bell: ['M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9', 'M10.3 21a1.94 1.94 0 0 0 3.4 0'],
  'bell-ring': [
    'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9',
    'M10.3 21a1.94 1.94 0 0 0 3.4 0',
    'M4 2C2.8 3.7 2 5.8 2 8',
    'M22 8c0-2.2-.8-4.3-2-6',
  ],
  'bell-off': [
    'M8.7 3A6 6 0 0 1 18 8c0 2.3.4 4.1 1 5.5',
    'M17 17H3s3-2 3-9a6 6 0 0 1 .3-1.9',
    'M10.3 21a1.94 1.94 0 0 0 3.4 0',
    'M2 2l20 20',
  ],
  search: ['circle:11,11,8', 'm21 21-4.3-4.3'],
  sliders: [
    'M4 21v-7',
    'M4 10V3',
    'M12 21v-9',
    'M12 8V3',
    'M20 21v-5',
    'M20 12V3',
    'M1 14h6',
    'M9 8h6',
    'M17 16h6',
  ],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  plus: ['M12 5v14', 'M5 12h14'],
  trash: [
    'M3 6h18',
    'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6',
    'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2',
    'M10 11v6',
    'M14 11v6',
  ],
  'volume-on': ['M11 5 6 9H2v6h4l5 4V5z', 'M15.5 8.5a5 5 0 0 1 0 7', 'M19 5a9 9 0 0 1 0 14'],
  'volume-off': ['M11 5 6 9H2v6h4l5 4V5z', 'm22 9-6 6', 'm16 9 6 6'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm7 10 5 5 5-5', 'M12 15V3'],
  candles: [
    'M8 3v3',
    'M8 18v3',
    'rect:6,6,4,12,1',
    'M16 2v5',
    'M16 17v5',
    'rect:14,7,4,10,1',
  ],
  'line-chart': ['M3 3v16a2 2 0 0 0 2 2h16', 'm19 9-5 5-4-4-3 3'],
  activity: 'M22 12h-4l-3 9L9 3l-3 9H2',
  zap: 'M4 14h7l-3 8 12-12h-7l3-8z',
  clock: ['circle:12,12,9', 'M12 7v5l3 2'],
  'alert-triangle': [
    'm10.3 3.9-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z',
    'M12 9v4',
    'M12 17h.01',
  ],
  wifi: ['M5 12.5a10 10 0 0 1 14 0', 'M8.5 16a5 5 0 0 1 7 0', 'M12 20h.01', 'M2 9a15 15 0 0 1 20 0'],
  'wifi-off': ['M2 2l20 20', 'M8.5 16a5 5 0 0 1 7 0', 'M12 20h.01', 'M5 12.5a10 10 0 0 1 4-2.5'],
  'refresh-cw': ['M21 12a9 9 0 1 1-2.6-6.4', 'M21 3v6h-6'],
  coins: ['circle:8,8,6', 'M18.1 10.4a6 6 0 1 1-8 7.7'],
  building: [
    'M3 21h18',
    'M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16',
    'M15 21v-9h2a2 2 0 0 1 2 2v7',
    'M9 7h2',
    'M9 11h2',
    'M9 15h2',
  ],
  list: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01'],
  history: ['M3 12a9 9 0 1 0 3-6.7L3 8', 'M3 3v5h5', 'M12 7v5l4 2'],
  target: ['circle:12,12,9', 'circle:12,12,5', 'circle:12,12,1'],
  percent: ['M19 5 5 19', 'circle:6.5,6.5,2.5', 'circle:17.5,17.5,2.5'],
  'bar-chart': ['M12 20V10', 'M18 20V4', 'M6 20v-4'],
  check: 'm5 13 4 4L19 7',
  dot: 'circle:12,12,4',
};

/**
 * @param {string} name
 * @param {{size?: number, className?: string, strokeWidth?: number}} [options]
 * @returns {SVGElement}
 */
export function icon(name, options = {}) {
  const size = options.size ?? 16;
  const node = svg('svg', {
    viewBox: '0 0 24 24',
    width: size,
    height: size,
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': options.strokeWidth ?? 2,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    focusable: 'false',
  });
  node.classList.add('icon');
  if (options.className) node.classList.add(options.className);

  const definition = PATHS[name];
  if (!definition) return node; // An unknown name renders as empty space, never a crash.

  for (const shape of Array.isArray(definition) ? definition : [definition]) {
    node.append(buildShape(shape));
  }
  return node;
}

function buildShape(shape) {
  if (shape.startsWith('circle:')) {
    const [cx, cy, r] = shape.slice(7).split(',').map(Number);
    return svg('circle', { cx, cy, r });
  }
  if (shape.startsWith('rect:')) {
    const [x, y, width, height, rx] = shape.slice(5).split(',').map(Number);
    return svg('rect', { x, y, width, height, rx: rx ?? 0 });
  }
  return svg('path', { d: shape });
}

/** The mark in the top bar: a rising line inside a rounded square. */
export function brandMark(size = 28) {
  const node = svg('svg', { viewBox: '0 0 32 32', width: size, height: size, 'aria-hidden': 'true' });
  node.classList.add('brand-mark');

  const gradient = svg('linearGradient', { id: 'brand-gradient', x1: '0', y1: '0', x2: '1', y2: '1' });
  gradient.append(svg('stop', { offset: '0', 'stop-color': '#6366f1' }));
  gradient.append(svg('stop', { offset: '1', 'stop-color': '#10b981' }));
  const defs = svg('defs');
  defs.append(gradient);
  node.append(defs);

  node.append(svg('rect', { x: 1, y: 1, width: 30, height: 30, rx: 9, fill: 'url(#brand-gradient)' }));
  node.append(
    svg('path', {
      d: 'M7 22l6-7 4 4 8-10',
      fill: 'none',
      stroke: '#0b0f17',
      'stroke-width': 2.6,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  );
  return node;
}
