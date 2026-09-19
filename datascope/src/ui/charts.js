/**
 * Charts: one price line, one volume column chart. Hand-built inline SVG - no
 * charting library, no external asset, nothing fetched at runtime.
 *
 * Both charts plot observations at equal horizontal spacing (one slot per row in
 * the file, not per calendar day) and share that mapping, so the two charts and
 * their cursors line up exactly. Days missing from the file are therefore not
 * drawn as gaps; the note under the charts says so.
 *
 * Each chart shows a single series, so neither carries a legend - there is only
 * one colour and the heading names what is plotted. Values are read from the
 * hover tooltip, the keyboard readout, or the data table below.
 */

import { clear, svg, svgText } from './dom.js';
import { formatCompact, formatDate, formatDateShort, formatMonth, formatPrice, formatInteger } from '../lib/format.js';

/**
 * Two geometries per chart. The SVG scales to its container, so on a narrow
 * screen a wide viewBox would shrink to a letterbox strip with unreadable text.
 * The compact pair is taller relative to its width and leaves less room for axis
 * labels, which is what keeps a phone-width chart legible.
 */
const GEOMETRIES = {
  price: {
    wide: { width: 840, height: 320, top: 18, right: 58, bottom: 36, left: 62 },
    compact: { width: 420, height: 300, top: 16, right: 30, bottom: 34, left: 52 },
  },
  volume: {
    wide: { width: 840, height: 200, top: 18, right: 58, bottom: 36, left: 62 },
    compact: { width: 420, height: 190, top: 16, right: 30, bottom: 34, left: 52 },
  },
};

/**
 * @param {'price'|'volume'} kind
 * @param {boolean} compact
 */
export function geometryFor(kind, compact) {
  return GEOMETRIES[kind][compact ? 'compact' : 'wide'];
}

const MAX_BAR_WIDTH = 24;
const BAR_GAP = 2;

/**
 * Human-friendly axis steps: 1, 2, 2.5, 5 or 10 times a power of ten.
 * @param {number} min
 * @param {number} max
 * @param {number} [target] Desired tick count.
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
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  const step = factor * magnitude;
  const lo = Math.floor(low / step) * step;
  const hi = Math.ceil(high / step) * step;
  const ticks = [];
  for (let value = lo; value <= hi + step / 2; value += step) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { ticks, lo, hi };
}

/**
 * Indices to label on the time axis: first, last and evenly spaced ones between.
 * @param {number} count
 * @param {number} [maxLabels]
 * @returns {number[]}
 */
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
  const raw = Math.floor((x - geometry.left) / slot);
  return Math.min(count - 1, Math.max(0, raw));
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
    const line = svg('line', {
      x1: geometry.left,
      x2: geometry.left + plotWidth,
      y1: y,
      y2: y,
    });
    line.classList.add('c-grid');
    root.append(line);

    const text = svg('text', { x: geometry.left - 8, y: y + 4, 'text-anchor': 'end' });
    text.classList.add('c-tick');
    root.append(svgText(text, formatTick(tick)));
  }
}

function drawTimeAxis(root, geometry, rows, maxLabels) {
  const y = geometry.height - geometry.bottom;
  const plotWidth = geometry.width - geometry.left - geometry.right;
  const baseline = svg('line', { x1: geometry.left, x2: geometry.left + plotWidth, y1: y, y2: y });
  baseline.classList.add('c-axis');
  root.append(baseline);

  const spanIsLong = rows.length > 1 && rows[rows.length - 1].date.slice(0, 7) !== rows[0].date.slice(0, 7);
  for (const index of axisIndices(rows.length, maxLabels)) {
    const text = svg('text', {
      x: slotCenter(geometry, index, rows.length),
      y: y + 20,
      'text-anchor': 'middle',
    });
    text.classList.add('c-tick');
    const label = spanIsLong ? formatMonth(rows[index].date) : formatDateShort(rows[index].date);
    root.append(svgText(text, label));
  }
}

function markerGroup(root, x, y, labelText, labelSide) {
  const dot = svg('circle', { cx: x, cy: y, r: 4.5 });
  dot.classList.add('c-dot');
  root.append(dot);

  if (labelText) {
    const text = svg('text', {
      x,
      y: labelSide === 'above' ? y - 12 : y + 20,
      'text-anchor': 'middle',
    });
    text.classList.add('c-point-label');
    root.append(svgText(text, labelText));
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

/**
 * Cursor behaviour shared by both charts: pointer hover, keyboard arrows, and a
 * live text readout that makes the values reachable without a mouse.
 */
function attachCursor({ container, node, geometry, rows, onMove }) {
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
    if (nextIndex < 0 || nextIndex >= rows.length) return;
    index = nextIndex;
    const x = slotCenter(geometry, index, rows.length);
    cursor.setAttribute('x1', String(x));
    cursor.setAttribute('x2', String(x));
    cursor.style.display = '';
    onMove(rows[index], index, x);
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
    place(indexFromX(geometry, x, rows.length));
  });
  node.addEventListener('pointerleave', hide);
  node.addEventListener('blur', hide);
  node.addEventListener('focus', () => place(index === -1 ? 0 : index));
  node.addEventListener('keydown', (event) => {
    const step = event.key === 'PageUp' || event.key === 'PageDown' ? 10 : 1;
    switch (event.key) {
      // The page is RTL but the time axis runs left to right, so ArrowRight
      // moves forward in time, matching what the reader sees.
      case 'ArrowRight':
      case 'PageUp':
        place(Math.min(rows.length - 1, (index === -1 ? -1 : index) + step));
        break;
      case 'ArrowLeft':
      case 'PageDown':
        place(Math.max(0, (index === -1 ? rows.length : index) - step));
        break;
      case 'Home':
        place(0);
        break;
      case 'End':
        place(rows.length - 1);
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

/**
 * @param {object} context
 * @param {HTMLElement} context.container Chart wrapper (position: relative).
 * @param {HTMLElement} context.tooltip Tooltip element inside the wrapper.
 * @param {HTMLElement} context.readout aria-live region for the keyboard cursor.
 * @param {{date: string, close: number, volume: number}[]} rows
 * @param {{symbol: string}} options
 */
function makeCursorHandler({ container, tooltip, readout, geometry, symbol }) {
  return (row, index, x) => {
    if (!row) {
      tooltip.hidden = true;
      return;
    }
    clear(tooltip);
    const dateLine = document.createElement('div');
    dateLine.className = 'tip-date';
    dateLine.dir = 'ltr';
    dateLine.textContent = formatDate(row.date);
    const closeLine = document.createElement('div');
    closeLine.textContent = `סגירה: ${formatPrice(row.close)}`;
    const volumeLine = document.createElement('div');
    volumeLine.textContent = `מחזור: ${formatInteger(row.volume)}`;
    tooltip.append(dateLine, closeLine, volumeLine);
    tooltip.hidden = false;

    const ratio = x / geometry.width;
    tooltip.style.left = `${ratio * 100}%`;
    tooltip.style.transform =
      ratio > 0.7 ? 'translate(-100%, 0)' : ratio < 0.3 ? 'translate(0, 0)' : 'translate(-50%, 0)';

    readout.textContent = `${symbol}, ${formatDate(row.date)}, סגירה ${formatPrice(
      row.close,
    )}, מחזור ${formatInteger(row.volume)}`;
  };
}

/**
 * Price line chart with an area wash, min/max direct labels and an end marker.
 *
 * @param {HTMLElement} container
 * @param {{date: string, close: number, volume: number}[]} rows Chronological.
 * @param {{symbol: string, tooltip: HTMLElement, readout: HTMLElement,
 *   minDate: string|null, maxDate: string|null}} options
 */
export function renderPriceChart(container, rows, options) {
  const geometry = geometryFor('price', options.compact);
  const maxLabels = options.compact ? 3 : 6;
  clear(container);
  if (rows.length === 0) return;

  const closes = rows.map((row) => row.close);
  const { ticks, lo, hi } = niceScale(Math.min(...closes), Math.max(...closes));
  const scaleY = yScaler(geometry, lo, hi);

  const label = `גרף מחיר סגירה עבור ${options.symbol}, ${rows.length} תצפיות, מ־${formatDate(
    rows[0].date,
  )} עד ${formatDate(rows[rows.length - 1].date)}. הערכים המדויקים מופיעים בטבלת הנתונים שמתחת לגרפים.`;
  const node = baseSvg(geometry, label);

  drawGrid(node, geometry, ticks, scaleY, (tick) => formatCompact(tick));
  drawTimeAxis(node, geometry, rows, maxLabels);

  const points = rows.map((row, index) => ({
    x: slotCenter(geometry, index, rows.length),
    y: scaleY(row.close),
    row,
  }));

  if (points.length > 1) {
    const baseline = geometry.height - geometry.bottom;
    const areaPath = [
      `M ${points[0].x} ${baseline}`,
      ...points.map((point) => `L ${point.x} ${point.y}`),
      `L ${points[points.length - 1].x} ${baseline}`,
      'Z',
    ].join(' ');
    const area = svg('path', { d: areaPath });
    area.classList.add('c-area');
    node.append(area);

    const line = svg('path', {
      d: points.map((point, i) => `${i === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' '),
      fill: 'none',
    });
    line.classList.add('c-line');
    node.append(line);
  }

  // Selective direct labels only: the extremes and the last value. A number on
  // every point would be unreadable at 250 observations.
  const minIndex = rows.findIndex((row) => row.date === options.minDate);
  const maxIndex = rows.findIndex((row) => row.date === options.maxDate);
  const lastIndex = rows.length - 1;
  const labelled = new Map();
  if (maxIndex >= 0) labelled.set(maxIndex, { text: formatPrice(rows[maxIndex].close), side: 'above' });
  if (minIndex >= 0 && !labelled.has(minIndex)) {
    labelled.set(minIndex, { text: formatPrice(rows[minIndex].close), side: 'below' });
  }
  if (!labelled.has(lastIndex)) {
    labelled.set(lastIndex, { text: formatPrice(rows[lastIndex].close), side: 'above' });
  }
  for (const [index, meta] of labelled) {
    const point = points[index];
    // Keep a label that would sit above the frame inside it instead.
    const side = meta.side === 'above' && point.y < geometry.top + 18 ? 'below' : meta.side;
    markerGroup(node, point.x, point.y, meta.text, side);
  }
  if (points.length === 1) markerGroup(node, points[0].x, points[0].y, null, 'above');

  container.append(node);
  attachCursor({
    container,
    node,
    geometry,
    rows,
    onMove: makeCursorHandler({ ...options, geometry, container }),
  });
}

/**
 * Volume column chart. Bars grow from a zero baseline - a bar chart without one
 * misstates the ratios between its own bars.
 *
 * @param {HTMLElement} container
 * @param {{date: string, close: number, volume: number}[]} rows
 * @param {{symbol: string, tooltip: HTMLElement, readout: HTMLElement}} options
 */
export function renderVolumeChart(container, rows, options) {
  const geometry = geometryFor('volume', options.compact);
  const maxLabels = options.compact ? 3 : 6;
  clear(container);
  if (rows.length === 0) return;

  const volumes = rows.map((row) => row.volume);
  const { ticks, lo, hi } = niceScale(0, Math.max(...volumes, 1), 4);
  const scaleY = yScaler(geometry, Math.min(0, lo), hi);
  const baseline = scaleY(0);

  const label = `גרף מחזור עבור ${options.symbol}, ${rows.length} תצפיות. הערכים המדויקים מופיעים בטבלת הנתונים שמתחת לגרפים.`;
  const node = baseSvg(geometry, label);

  drawGrid(node, geometry, ticks, scaleY, (tick) => formatCompact(tick));

  const plotWidth = geometry.width - geometry.left - geometry.right;
  const slot = plotWidth / rows.length;
  // A 2px surface gap separates neighbouring bars, and the data-end is rounded -
  // but only while the slot is wide enough for either to be visible.
  const wideSlots = slot - BAR_GAP >= 4;
  const barWidth = wideSlots ? Math.min(MAX_BAR_WIDTH, slot - BAR_GAP) : Math.max(0.8, slot * 0.8);

  rows.forEach((row, index) => {
    const center = slotCenter(geometry, index, rows.length);
    const top = scaleY(row.volume);
    const height = Math.max(row.volume > 0 ? 1 : 0, baseline - top);
    if (height <= 0) return;
    const x = center - barWidth / 2;
    const mark =
      barWidth >= 8 && height > 6
        ? svg('path', { d: roundedTopPath(x, baseline - height, barWidth, height, 4) })
        : svg('rect', { x, y: baseline - height, width: barWidth, height });
    mark.classList.add('c-bar');
    node.append(mark);
  });

  drawTimeAxis(node, geometry, rows, maxLabels);

  container.append(node);
  attachCursor({
    container,
    node,
    geometry,
    rows,
    onMove: makeCursorHandler({ ...options, geometry, container }),
  });
}
