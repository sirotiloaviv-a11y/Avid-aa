/**
 * The live price and volume charts: hand-built inline SVG, no charting library,
 * nothing fetched at runtime.
 *
 * Both charts plot the same candle window at the same horizontal positions, so
 * a spike in volume lines up with the price bar that caused it. Each shows a
 * single series, so neither carries a legend - the caption names what is
 * plotted, and exact values come from the hover tooltip or the keyboard readout.
 *
 * These redraw while prices move, so the caller throttles them with
 * requestAnimationFrame rather than rendering on every socket frame.
 */

import { clear, svg, svgText } from './dom.js';
import { formatClock, formatCompact, formatPrice } from '../lib/format.js';

const GEOMETRIES = {
  price: {
    wide: { width: 840, height: 300, top: 18, right: 58, bottom: 34, left: 64 },
    compact: { width: 420, height: 280, top: 16, right: 30, bottom: 32, left: 54 },
  },
  volume: {
    wide: { width: 840, height: 150, top: 14, right: 58, bottom: 34, left: 64 },
    compact: { width: 420, height: 150, top: 12, right: 30, bottom: 32, left: 54 },
  },
};

const MAX_BAR_WIDTH = 24;
const BAR_GAP = 2;

/** @param {'price'|'volume'} kind @param {boolean} compact */
export function geometryFor(kind, compact) {
  return GEOMETRIES[kind][compact ? 'compact' : 'wide'];
}

/**
 * Axis steps at 1, 2, 2.5, 5 or 10 times a power of ten.
 * @returns {{ticks: number[], lo: number, hi: number}}
 */
export function niceScale(min, max, target = 5) {
  let low = min;
  let high = max;
  if (!Number.isFinite(low) || !Number.isFinite(high)) return { ticks: [0, 1], lo: 0, hi: 1 };
  if (low === high) {
    const pad = Math.abs(low) * 0.05 || 1;
    low -= pad;
    high += pad;
  }
  const rawStep = (high - low) / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const factor =
    normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  const step = factor * magnitude;
  const lo = Math.floor(low / step) * step;
  const hi = Math.ceil(high / step) * step;
  const ticks = [];
  for (let value = lo; value <= hi + step / 2; value += step) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { ticks, lo, hi };
}

/** Evenly spaced label indices, always including the first and the last. */
export function axisIndices(count, maxLabels = 6) {
  if (count <= 0) return [];
  if (count <= maxLabels) return Array.from({ length: count }, (_, i) => i);
  const step = (count - 1) / (maxLabels - 1);
  const picked = new Set();
  for (let i = 0; i < maxLabels; i += 1) picked.add(Math.round(i * step));
  return [...picked].sort((a, b) => a - b);
}

function slotCenter(geometry, index, count) {
  const plotWidth = geometry.width - geometry.left - geometry.right;
  const slot = plotWidth / Math.max(1, count);
  return geometry.left + (index + 0.5) * slot;
}

function indexFromX(geometry, x, count) {
  const plotWidth = geometry.width - geometry.left - geometry.right;
  const slot = plotWidth / Math.max(1, count);
  return Math.min(count - 1, Math.max(0, Math.floor((x - geometry.left) / slot)));
}

function yScaler(geometry, lo, hi) {
  const plotHeight = geometry.height - geometry.top - geometry.bottom;
  const span = hi - lo || 1;
  return (value) => geometry.top + plotHeight - ((value - lo) / span) * plotHeight;
}

function baseSvg(geometry, label) {
  const node = svg('svg', {
    viewBox: `0 0 ${geometry.width} ${geometry.height}`,
    preserveAspectRatio: 'xMidYMid meet',
    role: 'img',
    'aria-label': label,
    tabindex: '0',
    focusable: 'true',
  });
  node.classList.add('chart-svg');
  return node;
}

function drawGrid(root, geometry, ticks, scaleY, formatTick) {
  const plotWidth = geometry.width - geometry.left - geometry.right;
  for (const tick of ticks) {
    const y = scaleY(tick);
    const line = svg('line', { x1: geometry.left, x2: geometry.left + plotWidth, y1: y, y2: y });
    line.classList.add('c-grid');
    root.append(line);

    const text = svg('text', { x: geometry.left - 8, y: y + 4, 'text-anchor': 'end' });
    text.classList.add('c-tick');
    root.append(svgText(text, formatTick(tick)));
  }
}

function drawTimeAxis(root, geometry, candles, maxLabels) {
  const y = geometry.height - geometry.bottom;
  const plotWidth = geometry.width - geometry.left - geometry.right;
  const baseline = svg('line', { x1: geometry.left, x2: geometry.left + plotWidth, y1: y, y2: y });
  baseline.classList.add('c-axis');
  root.append(baseline);

  for (const index of axisIndices(candles.length, maxLabels)) {
    const text = svg('text', {
      x: slotCenter(geometry, index, candles.length),
      y: y + 19,
      'text-anchor': 'middle',
    });
    text.classList.add('c-tick');
    root.append(svgText(text, formatClock(candles[index].t, { seconds: false })));
  }
}

function roundedTopPath(x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height);
  const bottom = y + height;
  return [
    `M ${x} ${bottom}`,
    `V ${y + r}`,
    `Q ${x} ${y} ${x + r} ${y}`,
    `H ${x + width - r}`,
    `Q ${x + width} ${y} ${x + width} ${y + r}`,
    `V ${bottom}`,
    'Z',
  ].join(' ');
}

/** Pointer and keyboard cursor, shared by both charts. */
function attachCursor({ node, geometry, candles, onMove }) {
  const cursor = svg('line', {
    y1: geometry.top,
    y2: geometry.height - geometry.bottom,
    x1: 0,
    x2: 0,
  });
  cursor.classList.add('c-cursor');
  cursor.style.display = 'none';
  node.append(cursor);

  let index = -1;

  function place(nextIndex) {
    if (nextIndex < 0 || nextIndex >= candles.length) return;
    index = nextIndex;
    const x = slotCenter(geometry, index, candles.length);
    cursor.setAttribute('x1', String(x));
    cursor.setAttribute('x2', String(x));
    cursor.style.display = '';
    onMove(candles[index], index, x);
  }

  function hide() {
    index = -1;
    cursor.style.display = 'none';
    onMove(null, -1, 0);
  }

  node.addEventListener('pointermove', (event) => {
    const box = node.getBoundingClientRect();
    if (box.width === 0) return;
    const x = ((event.clientX - box.left) / box.width) * geometry.width;
    place(indexFromX(geometry, x, candles.length));
  });
  node.addEventListener('pointerleave', hide);
  node.addEventListener('blur', hide);
  node.addEventListener('focus', () => place(index === -1 ? candles.length - 1 : index));
  node.addEventListener('keydown', (event) => {
    const step = event.key === 'PageUp' || event.key === 'PageDown' ? 10 : 1;
    switch (event.key) {
      // The page is RTL but time runs left to right, so ArrowRight moves
      // forward in time, matching what the reader sees.
      case 'ArrowRight':
      case 'PageUp':
        place(Math.min(candles.length - 1, (index === -1 ? -1 : index) + step));
        break;
      case 'ArrowLeft':
      case 'PageDown':
        place(Math.max(0, (index === -1 ? candles.length : index) - step));
        break;
      case 'Home':
        place(0);
        break;
      case 'End':
        place(candles.length - 1);
        break;
      case 'Escape':
        hide();
        return;
      default:
        return;
    }
    event.preventDefault();
  });
}

function makeCursorHandler({ tooltip, readout, geometry, label }) {
  return (candle, index, x) => {
    if (!candle) {
      tooltip.hidden = true;
      return;
    }
    clear(tooltip);
    const time = document.createElement('div');
    time.className = 'tip-date';
    time.dir = 'ltr';
    time.textContent = formatClock(candle.t);
    const price = document.createElement('div');
    price.textContent = `מחיר: ${formatPrice(candle.close)}`;
    const volume = document.createElement('div');
    volume.textContent = `מחזור: ${formatCompact(candle.volume)}`;
    tooltip.append(time, price, volume);
    tooltip.hidden = false;

    const ratio = x / geometry.width;
    tooltip.style.left = `${ratio * 100}%`;
    tooltip.style.transform =
      ratio > 0.7 ? 'translate(-100%, 0)' : ratio < 0.3 ? 'translate(0, 0)' : 'translate(-50%, 0)';

    if (readout) {
      readout.textContent = `${label}, ${formatClock(candle.t)}, מחיר ${formatPrice(
        candle.close,
      )}, מחזור ${formatCompact(candle.volume)}`;
    }
  };
}

/**
 * Price line with an area wash and a marker on the latest point.
 *
 * @param {HTMLElement} container
 * @param {import('../lib/model.js').Candle[]} candles Ascending by time.
 * @param {{label: string, tooltip: HTMLElement, readout?: HTMLElement,
 *   compact?: boolean, referencePrice?: number|null}} options
 */
export function renderPriceChart(container, candles, options) {
  const geometry = geometryFor('price', options.compact);
  clear(container);
  if (candles.length === 0) return;

  const closes = candles.map((candle) => candle.close);
  let min = Math.min(...closes);
  let max = Math.max(...closes);
  // Keep the reference price inside the frame: a chart that crops the level the
  // day's change is measured against invites the wrong reading.
  if (typeof options.referencePrice === 'number' && Number.isFinite(options.referencePrice)) {
    min = Math.min(min, options.referencePrice);
    max = Math.max(max, options.referencePrice);
  }
  const { ticks, lo, hi } = niceScale(min, max);
  const scaleY = yScaler(geometry, lo, hi);

  const node = baseSvg(
    geometry,
    `גרף מחיר חי עבור ${options.label}, ${candles.length} נרות. הערך המדויק זמין בהצבעה על הגרף או בניווט מקלדת.`,
  );

  drawGrid(node, geometry, ticks, scaleY, (tick) => formatCompact(tick));
  drawTimeAxis(node, geometry, candles, options.compact ? 3 : 6);

  if (typeof options.referencePrice === 'number' && Number.isFinite(options.referencePrice)) {
    const y = scaleY(options.referencePrice);
    const line = svg('line', {
      x1: geometry.left,
      x2: geometry.width - geometry.right,
      y1: y,
      y2: y,
    });
    line.classList.add('c-reference');
    node.append(line);
  }

  const points = candles.map((candle, index) => ({
    x: slotCenter(geometry, index, candles.length),
    y: scaleY(candle.close),
  }));

  if (points.length > 1) {
    const baseline = geometry.height - geometry.bottom;
    const area = svg('path', {
      d: [
        `M ${points[0].x} ${baseline}`,
        ...points.map((point) => `L ${point.x} ${point.y}`),
        `L ${points[points.length - 1].x} ${baseline}`,
        'Z',
      ].join(' '),
    });
    area.classList.add('c-area');
    node.append(area);

    const line = svg('path', {
      d: points.map((point, i) => `${i === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' '),
      fill: 'none',
    });
    line.classList.add('c-line');
    node.append(line);
  }

  // One direct label, on the live price. Labelling every point would be
  // unreadable at 240 candles and pointless while they are all moving.
  const last = points[points.length - 1];
  const dot = svg('circle', { cx: last.x, cy: last.y, r: 4.5 });
  dot.classList.add('c-dot', 'c-dot-live');
  node.append(dot);

  const label = svg('text', {
    x: last.x,
    y: last.y < geometry.top + 18 ? last.y + 20 : last.y - 12,
    'text-anchor': 'end',
  });
  label.classList.add('c-point-label');
  node.append(svgText(label, formatPrice(candles[candles.length - 1].close)));

  container.append(node);
  attachCursor({
    node,
    geometry,
    candles,
    onMove: makeCursorHandler({ ...options, geometry }),
  });
}

/**
 * Volume columns, from a zero baseline - a volume chart without one misstates
 * the ratios between its own bars.
 *
 * @param {HTMLElement} container
 * @param {import('../lib/model.js').Candle[]} candles
 * @param {{label: string, tooltip: HTMLElement, readout?: HTMLElement, compact?: boolean}} options
 */
export function renderVolumeChart(container, candles, options) {
  const geometry = geometryFor('volume', options.compact);
  clear(container);
  if (candles.length === 0) return;

  const volumes = candles.map((candle) => candle.volume);
  const { ticks, lo, hi } = niceScale(0, Math.max(...volumes, 1), 3);
  const scaleY = yScaler(geometry, Math.min(0, lo), hi);
  const baseline = scaleY(0);

  const node = baseSvg(geometry, `גרף מחזור חי עבור ${options.label}, ${candles.length} נרות.`);
  drawGrid(node, geometry, ticks, scaleY, (tick) => formatCompact(tick));

  const plotWidth = geometry.width - geometry.left - geometry.right;
  const slot = plotWidth / candles.length;
  // A 2px surface gap and a rounded data-end, but only while the slot is wide
  // enough for either to be visible.
  const wide = slot - BAR_GAP >= 4;
  const barWidth = wide ? Math.min(MAX_BAR_WIDTH, slot - BAR_GAP) : Math.max(0.8, slot * 0.8);

  candles.forEach((candle, index) => {
    const center = slotCenter(geometry, index, candles.length);
    const top = scaleY(candle.volume);
    const height = Math.max(candle.volume > 0 ? 1 : 0, baseline - top);
    if (height <= 0) return;
    const x = center - barWidth / 2;
    const mark =
      barWidth >= 8 && height > 6
        ? svg('path', { d: roundedTopPath(x, baseline - height, barWidth, height, 4) })
        : svg('rect', { x, y: baseline - height, width: barWidth, height });
    mark.classList.add('c-bar');
    if (index === candles.length - 1) mark.classList.add('c-bar-live');
    node.append(mark);
  });

  drawTimeAxis(node, geometry, candles, options.compact ? 3 : 6);

  container.append(node);
  attachCursor({
    node,
    geometry,
    candles,
    onMove: makeCursorHandler({ ...options, geometry }),
  });
}
