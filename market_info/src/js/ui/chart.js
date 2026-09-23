import { esc } from '../dom.js';
import { formatPrice, formatCompact, formatShortDate, formatDateTime } from '../format.js';

const HEIGHT = 280;
const PAD = { top: 14, right: 64, bottom: 26, left: 10 };
const VOLUME_SHARE = 0.22;

// Price line with a volume strip underneath. Time runs left to right, as in
// every financial chart, even though the page itself is right-to-left.
export function renderChart(container, bars, { currency = 'USD', tz = 'UTC', volumeLabel = 'נפח' } = {}) {
  if (!bars.length) {
    container.innerHTML = '<div class="state state-empty">אין נתוני מחיר להצגה.</div>';
    return;
  }
  container.classList.add('chart');
  container.setAttribute('dir', 'ltr');

  const draw = () => {
    const width = Math.max(280, Math.floor(container.clientWidth || 600));
    container.innerHTML = svg(bars, width, currency, tz) +
      '<div class="chart-tip" hidden></div>';
    bindHover(container, bars, width, currency, tz, volumeLabel);
  };
  draw();

  if (typeof ResizeObserver !== 'undefined') {
    let lastWidth = container.clientWidth;
    const ro = new ResizeObserver(() => {
      if (!container.isConnected) { ro.disconnect(); return; }
      if (Math.abs(container.clientWidth - lastWidth) < 4) return;
      lastWidth = container.clientWidth;
      draw();
    });
    ro.observe(container);
  }
}

function scales(bars, width) {
  const closes = bars.map((b) => b.close);
  // Missing high/low (e.g. price-only series) fall back to the close; they
  // are never estimated.
  let min = Math.min(...bars.map((b) => b.low ?? b.close), ...closes);
  let max = Math.max(...bars.map((b) => b.high ?? b.close), ...closes);
  const padding = (max - min) * 0.08 || max * 0.01;
  min -= padding;
  max += padding;
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const priceH = plotH * (1 - VOLUME_SHARE);
  const maxVol = Math.max(0, ...bars.map((b) => b.volume ?? 0)) || 1;
  const step = bars.length > 1 ? plotW / (bars.length - 1) : 0;
  return {
    x: (i) => PAD.left + (bars.length > 1 ? i * step : plotW / 2),
    y: (v) => PAD.top + (1 - (v - min) / (max - min)) * priceH,
    vy: (v) => PAD.top + plotH - (v / maxVol) * plotH * VOLUME_SHARE * 0.9,
    min, max, plotW, plotH, priceH, step,
  };
}

function svg(bars, width, currency, tz) {
  const s = scales(bars, width);
  const pts = bars.map((b, i) => `${s.x(i).toFixed(1)},${s.y(b.close).toFixed(1)}`);
  const baseY = PAD.top + s.priceH;
  const area = `M${pts[0]} L${pts.join(' L')} L${s.x(bars.length - 1).toFixed(1)},${baseY} L${s.x(0).toFixed(1)},${baseY} Z`;
  const barW = Math.max(1, Math.min(10, s.step * 0.6 || 6));

  const ticks = 4;
  let grid = '';
  for (let i = 0; i <= ticks; i++) {
    const v = s.min + ((s.max - s.min) * i) / ticks;
    const y = s.y(v);
    grid += `<line class="grid" x1="${PAD.left}" x2="${width - PAD.right}" y1="${y}" y2="${y}"/>` +
      `<text class="axis" x="${width - PAD.right + 6}" y="${y + 4}">${esc(formatPrice(v, currency))}</text>`;
  }
  const labelEvery = Math.max(1, Math.ceil(bars.length / Math.max(2, Math.floor(width / 90))));
  let xLabels = '';
  bars.forEach((b, i) => {
    if (i % labelEvery !== 0 && i !== bars.length - 1) return;
    if (i !== bars.length - 1 && bars.length - 1 - i < labelEvery / 2) return;
    xLabels += `<text class="axis" text-anchor="middle" x="${s.x(i)}" y="${HEIGHT - 6}">${esc(formatShortDate(b.t, tz))}</text>`;
  });
  const volumes = bars.map((b, i) => {
    if (b.volume === null || b.volume === undefined) return '';
    const up = i === 0 || b.close >= bars[i - 1].close;
    const y = s.vy(b.volume);
    return `<rect class="vol ${up ? 'up' : 'down'}" x="${(s.x(i) - barW / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${(PAD.top + s.plotH - y).toFixed(1)}"/>`;
  }).join('');

  return `<svg width="${width}" height="${HEIGHT}" viewBox="0 0 ${width} ${HEIGHT}" role="img"
      aria-label="גרף מחיר ונפח (נתוני הדגמה)">
    ${grid}
    ${volumes}
    <path class="area" d="${area}"/>
    <polyline class="line" points="${pts.join(' ')}"/>
    ${xLabels}
    <line class="cursor" x1="0" x2="0" y1="${PAD.top}" y2="${PAD.top + s.plotH}" visibility="hidden"/>
    <circle class="dot" r="4" cx="0" cy="0" visibility="hidden"/>
    <rect class="hit" x="${PAD.left}" y="${PAD.top}" width="${s.plotW}" height="${s.plotH}"/>
  </svg>`;
}

function bindHover(container, bars, width, currency, tz, volumeLabel) {
  const s = scales(bars, width);
  const svgEl = container.querySelector('svg');
  const cursor = svgEl.querySelector('.cursor');
  const dot = svgEl.querySelector('.dot');
  const tip = container.querySelector('.chart-tip');
  const hit = svgEl.querySelector('.hit');

  const show = (evt) => {
    const rect = svgEl.getBoundingClientRect();
    const px = ((evt.clientX - rect.left) / rect.width) * width;
    const i = Math.max(0, Math.min(bars.length - 1, Math.round((px - PAD.left) / (s.step || 1))));
    const b = bars[i];
    const x = s.x(i);
    cursor.setAttribute('x1', x);
    cursor.setAttribute('x2', x);
    cursor.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x);
    dot.setAttribute('cy', s.y(b.close));
    dot.setAttribute('visibility', 'visible');
    tip.hidden = false;
    tip.innerHTML = `<div>${esc(formatDateTime(b.t, tz))}</div>
      <div><span class="muted">מחיר</span> ${esc(formatPrice(b.close, currency))}</div>
      <div><span class="muted">${esc(volumeLabel)}</span> ${b.volume === null || b.volume === undefined ? 'אין נתון' : esc(formatCompact(b.volume))}</div>`;
    const left = (x / width) * rect.width;
    tip.style.left = `${Math.min(Math.max(left - 70, 0), rect.width - 150)}px`;
  };
  const hide = () => {
    cursor.setAttribute('visibility', 'hidden');
    dot.setAttribute('visibility', 'hidden');
    tip.hidden = true;
  };
  hit.addEventListener('pointermove', show);
  hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', hide);
}
