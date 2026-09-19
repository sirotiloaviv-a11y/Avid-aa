/**
 * The live price and volume charts: hand-built inline SVG, no charting library,
 * nothing fetched at runtime.
 *
 * Two price modes share one geometry and one cursor:
 *   - candles: wick plus body per bucket, the trading-platform default,
 *   - line: a glowing path with an area wash under it.
 *
 * Up candles are *filled* and down candles are *hollow*. That is not decoration:
 * emerald and red sit right at the colour-blind separation floor (ΔE 8.1 under
 * deuteranopia), so direction gets a second channel that survives without hue.
 *
 * The volume chart plots the same buckets at the same x positions, so a spike in
 * volume lines up with the candle that caused it.
 *
 * These redraw while prices move, so the caller throttles them with
 * requestAnimationFrame rather than rendering on every socket frame.
 */

import { clear, svg, svgText } from './dom.js';
import { formatAxisPrice, formatClock, formatCompact, formatPrice } from '../lib/format.js';

const GEOMETRIES = {
  price: {
    wide: { width: 880, height: 290, top: 16, right: 62, bottom: 28, left: 16 },
    compact: { width: 420, height: 240, top: 14, right: 52, bottom: 26, left: 10 },
  },
  volume: {
    wide: { width: 880, height: 92, top: 10, right: 62, bottom: 22, left: 16 },
    compact: { width: 420, height: 84, top: 8, right: 52, bottom: 22, left: 10 },
  },
};

/** How many buckets each mode shows. Candles need room to be readable. */
const VISIBLE = {
  candles: { wide: 110, compact: 46 },
  line: { wide: 240, compact: 120 },
};

const MAX_BAR_WIDTH = 18;
const BAR_GAP = 2;

/** @param {'price'|'volume'} kind @param {boolean} compact */
export function geometryFor(kind, compact) {
  return GEOMETRIES[kind][compact ? 'compact' : 'wide'];
}

/**
 * The slice of history a mode shows.
 * @param {import('../lib/model.js').Candle[]} candles
 * @param {'candles'|'line'} mode
 * @param {boolean} compact
 */
export function visibleWindow(candles, mode, compact) {
  const limit = VISIBLE[mode]?.[compact ? 'compact' : 'wide'] ?? 120;
  return candles.length > limit ? candles.slice(-limit) : candles;
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

function plotWidth(geometry) {
  return geometry.width - geometry.left - geometry.right;
}

function slotCenter(geometry, index, count) {
  const slot = plotWidth(geometry) / Math.max(1, count);
  return geometry.left + (index + 0.5) * slot;
}

function indexFromX(geometry, x, count) {
  const slot = plotWidth(geometry) / Math.max(1, count);
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

/** Price axis on the inline end, the way a trading chart puts it. */
function drawGrid(root, geometry, ticks, scaleY, formatTick) {
  for (const tick of ticks) {
    const y = scaleY(tick);
    const line = svg('line', {
      x1: geometry.left,
      x2: geometry.left + plotWidth(geometry),
      y1: y,
      y2: y,
    });
    line.classList.add('c-grid');
    root.append(line);

    const text = svg('text', {
      x: geometry.left + plotWidth(geometry) + 8,
      y: y + 3.5,
      'text-anchor': 'start',
    });
    text.classList.add('c-tick');
    root.append(svgText(text, formatTick(tick)));
  }
}

function drawTimeAxis(root, geometry, candles, maxLabels) {
  const y = geometry.height - geometry.bottom;
  const baseline = svg('line', {
    x1: geometry.left,
    x2: geometry.left + plotWidth(geometry),
    y1: y,
    y2: y,
  });
  baseline.classList.add('c-axis');
  root.append(baseline);

  for (const index of axisIndices(candles.length, maxLabels)) {
    const text = svg('text', {
      x: slotCenter(geometry, index, candles.length),
      y: y + 16,
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

/** Which way a candle closed. Flat counts as up, as every platform does. */
function candleDirection(candle) {
  return candle.close >= candle.open ? 'dir-up' : 'dir-down';
}

/* ------------------------------------------------------------------- cursor */

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

function makeCursorHandler({ tooltip, readout, geometry, label, withOhlc }) {
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
    tooltip.append(time);

    if (withOhlc) {
      // The four values a candle actually encodes, so the mark is readable as
      // data rather than as a shape.
      for (const [name, value] of [
        ['פתיחה', candle.open],
        ['גבוה', candle.high],
        ['נמוך', candle.low],
        ['סגירה', candle.close],
      ]) {
        const row = document.createElement('div');
        row.textContent = `${name}: ${formatPrice(value)}`;
        tooltip.append(row);
      }
    } else {
      const price = document.createElement('div');
      price.textContent = `מחיר: ${formatPrice(candle.close)}`;
      tooltip.append(price);
    }

    const volume = document.createElement('div');
    volume.textContent = `מחזור: ${formatCompact(candle.volume)}`;
    tooltip.append(volume);
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

/* -------------------------------------------------------------- price chart */

/**
 * @param {HTMLElement} container
 * @param {import('../lib/model.js').Candle[]} allCandles Ascending by time.
 * @param {{label: string, tooltip: HTMLElement, readout?: HTMLElement,
 *   compact?: boolean, mode?: 'candles'|'line', referencePrice?: number|null}} options
 * @returns {import('../lib/model.js').Candle[]} The window actually drawn.
 */
export function renderPriceChart(container, allCandles, options) {
  const mode = options.mode === 'line' ? 'line' : 'candles';
  const geometry = geometryFor('price', options.compact);
  clear(container);
  if (allCandles.length === 0) return [];

  const candles = visibleWindow(allCandles, mode, options.compact);

  // Candles need the full high/low range in frame; a line only needs closes.
  const lows = mode === 'candles' ? candles.map((c) => c.low) : candles.map((c) => c.close);
  const highs = mode === 'candles' ? candles.map((c) => c.high) : candles.map((c) => c.close);
  let min = Math.min(...lows);
  let max = Math.max(...highs);
  if (typeof options.referencePrice === 'number' && Number.isFinite(options.referencePrice)) {
    // Keep the level the day's change is measured against inside the frame.
    min = Math.min(min, options.referencePrice);
    max = Math.max(max, options.referencePrice);
  }
  const { ticks, lo, hi } = niceScale(min, max);
  const scaleY = yScaler(geometry, lo, hi);

  const node = baseSvg(
    geometry,
    `גרף מחיר חי עבור ${options.label}, ${candles.length} נרות של דקה. הערכים המדויקים זמינים בהצבעה על הגרף או בניווט מקלדת.`,
  );

  drawGrid(node, geometry, ticks, scaleY, (tick) => formatAxisPrice(tick));

  if (typeof options.referencePrice === 'number' && Number.isFinite(options.referencePrice)) {
    const y = scaleY(options.referencePrice);
    const line = svg('line', { x1: geometry.left, x2: geometry.left + plotWidth(geometry), y1: y, y2: y });
    line.classList.add('c-reference');
    node.append(line);
  }

  if (mode === 'candles') drawCandles(node, geometry, candles, scaleY);
  else drawLine(node, geometry, candles, scaleY);

  drawTimeAxis(node, geometry, candles, options.compact ? 3 : 6);

  container.append(node);
  attachCursor({
    node,
    geometry,
    candles,
    onMove: makeCursorHandler({ ...options, geometry, withOhlc: mode === 'candles' }),
  });
  return candles;
}

function drawCandles(root, geometry, candles, scaleY) {
  const slot = plotWidth(geometry) / candles.length;
  const bodyWidth = Math.max(1.5, Math.min(14, slot - 2));
  const lastIndex = candles.length - 1;

  candles.forEach((candle, index) => {
    const direction = candleDirection(candle);
    const isLive = index === lastIndex;
    const center = slotCenter(geometry, index, candles.length);

    const wick = svg('line', {
      x1: center,
      x2: center,
      y1: scaleY(candle.high),
      y2: scaleY(candle.low),
    });
    wick.classList.add('c-candle-wick', direction);
    if (isLive) wick.classList.add('is-live');
    root.append(wick);

    const top = scaleY(Math.max(candle.open, candle.close));
    const bottom = scaleY(Math.min(candle.open, candle.close));
    // A doji would be invisible at zero height, so it keeps a 1px body.
    const height = Math.max(1, bottom - top);

    const body = svg('rect', {
      x: center - bodyWidth / 2,
      y: top,
      width: bodyWidth,
      height,
      rx: Math.min(1.5, bodyWidth / 3),
    });
    body.classList.add('c-candle-body', direction);
    if (isLive) body.classList.add('is-live');
    root.append(body);
  });
}

function drawLine(root, geometry, candles, scaleY) {
  const points = candles.map((candle, index) => ({
    x: slotCenter(geometry, index, candles.length),
    y: scaleY(candle.close),
  }));

  // The period's own direction tints the line and the wash beneath it.
  const rising = candles[candles.length - 1].close >= candles[0].close;
  const direction = rising ? 'dir-up' : 'dir-down';
  const gradientId = `ds-area-${rising ? 'up' : 'down'}`;

  const defs = svg('defs');
  const gradient = svg('linearGradient', { id: gradientId, x1: '0', y1: '0', x2: '0', y2: '1' });
  gradient.append(
    svg('stop', {
      offset: '0',
      'stop-color': rising ? '#10b981' : '#ef4444',
      'stop-opacity': '0.28',
    }),
  );
  gradient.append(
    svg('stop', {
      offset: '1',
      'stop-color': rising ? '#10b981' : '#ef4444',
      'stop-opacity': '0',
    }),
  );
  defs.append(gradient);
  root.append(defs);

  if (points.length > 1) {
    const baseline = geometry.height - geometry.bottom;
    const area = svg('path', {
      d: [
        `M ${points[0].x} ${baseline}`,
        ...points.map((point) => `L ${point.x} ${point.y}`),
        `L ${points[points.length - 1].x} ${baseline}`,
        'Z',
      ].join(' '),
      fill: `url(#${gradientId})`,
    });
    area.classList.add('c-area');
    root.append(area);

    const line = svg('path', {
      d: points.map((point, i) => `${i === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' '),
      fill: 'none',
    });
    line.classList.add('c-line', direction);
    root.append(line);
  }

  // One direct label, on the live price. Labelling every point would be
  // unreadable at this density and pointless while they are all moving.
  const last = points[points.length - 1];
  const dot = svg('circle', { cx: last.x, cy: last.y, r: 4 });
  dot.classList.add('c-dot', 'c-dot-live');
  root.append(dot);

  const label = svg('text', {
    x: last.x - 8,
    y: last.y < geometry.top + 16 ? last.y + 18 : last.y - 10,
    'text-anchor': 'end',
  });
  label.classList.add('c-point-label');
  root.append(svgText(label, formatPrice(candles[candles.length - 1].close)));
}

/* ------------------------------------------------------------- volume chart */

/**
 * Volume columns from a zero baseline, tinted by the direction of the candle
 * they belong to - a volume chart without a zero baseline misstates the ratios
 * between its own bars.
 *
 * @param {HTMLElement} container
 * @param {import('../lib/model.js').Candle[]} candles The same window the price
 *   chart drew, so the two line up bucket for bucket.
 * @param {{label: string, tooltip: HTMLElement, readout?: HTMLElement, compact?: boolean}} options
 */
export function renderVolumeChart(container, candles, options) {
  const geometry = geometryFor('volume', options.compact);
  clear(container);
  if (candles.length === 0) return;

  const volumes = candles.map((candle) => candle.volume);
  const { ticks, lo, hi } = niceScale(0, Math.max(...volumes, 1), 2);
  const scaleY = yScaler(geometry, Math.min(0, lo), hi);
  const baseline = scaleY(0);

  const node = baseSvg(geometry, `גרף מחזור חי עבור ${options.label}, ${candles.length} נרות.`);
  drawGrid(node, geometry, ticks, scaleY, (tick) => formatCompact(tick));

  const slot = plotWidth(geometry) / candles.length;
  const wide = slot - BAR_GAP >= 4;
  const barWidth = wide ? Math.min(MAX_BAR_WIDTH, slot - BAR_GAP) : Math.max(0.8, slot * 0.8);
  const lastIndex = candles.length - 1;

  candles.forEach((candle, index) => {
    const center = slotCenter(geometry, index, candles.length);
    const top = scaleY(candle.volume);
    const height = Math.max(candle.volume > 0 ? 1 : 0, baseline - top);
    if (height <= 0) return;
    const x = center - barWidth / 2;
    const mark =
      barWidth >= 6 && height > 5
        ? svg('path', { d: roundedTopPath(x, baseline - height, barWidth, height, 2) })
        : svg('rect', { x, y: baseline - height, width: barWidth, height });
    mark.classList.add('c-bar', candleDirection(candle));
    if (index === lastIndex) mark.classList.add('c-bar-live');
    node.append(mark);
  });

  container.append(node);
  attachCursor({
    node,
    geometry,
    candles,
    onMove: makeCursorHandler({ ...options, geometry, withOhlc: false }),
  });
}
