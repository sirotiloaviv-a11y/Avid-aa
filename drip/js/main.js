import { initShop } from './shop.js';
import { buildTimeline, roundedPolygon } from './scene.js';

const html = document.documentElement;
const stage = document.querySelector('[data-stage]');
const shapeSvg = document.querySelector('[data-shape]');
const shapePath = shapeSvg.querySelector('path');
const flat = document.querySelector('[data-flat]');
const canvas = document.querySelector('[data-canvas]');

const bottleState = { x: 0.5, y: 0.5, h: 0.6, tilt: 0, spin: 0, lean: 0, shadow: 0 };
const shapeState = { ax: 0, ay: 0, bx: 0, by: 0, cx: 0, cy: 0, dx: 0, dy: 0, r: 0 };

let bottle3d = null;
let dirty = true;
let size = { w: 0, h: 0, sh: 0 };

const shop = initShop({
  onColor(c, initial) {
    bottle3d?.setColor(c.body, c.ink, initial);
    dirty = true;
  },
});

function measure() {
  size = { w: stage.clientWidth, h: stage.clientHeight, sh: shapeSvg.clientHeight || stage.clientHeight };
  shapeSvg.setAttribute('viewBox', `0 0 ${size.w} ${size.sh}`);
  bottle3d?.resize();
  dirty = true;
}

function drawShape() {
  const { w, h, sh } = size;
  const s = shapeState;
  // Points at or beyond the bottom edge stick to the bottom of the (taller)
  // shape layer, so the black floor has no gap under a collapsing toolbar.
  const py = (y) => (y >= 0.999 ? sh + (y - 1) * h : y * h);
  const pts = [[s.ax * w, py(s.ay)], [s.bx * w, py(s.by)], [s.cx * w, py(s.cy)], [s.dx * w, py(s.dy)]];
  shapePath.setAttribute('d', roundedPolygon(pts, s.r));
}

function drawFlat() {
  // Flat fallback bottle (before WebGL is ready, or when it's unavailable).
  const s = bottleState;
  const hPx = s.h * size.h;
  const k = hPx / 1000;
  flat.style.transform = `translate(${s.x * size.w - 155}px, ${s.y * size.h - 500}px) rotate(${s.tilt}deg) scale(${k})`;
}

function frame() {
  if (!dirty && !bottle3d?.needsFrame) return;
  dirty = false;
  if (!html.classList.contains('is-cinematic')) return;
  drawShape();
  if (bottle3d) bottle3d.render(bottleState);
  else drawFlat();
}

async function load3D() {
  try {
    const { createBottle3D } = await import('./bottle3d.js');
    const b = await createBottle3D(canvas);
    bottle3d = b;
    b.resize();
    b.setColor(shop.color.body, shop.color.ink, true);
    b.render(bottleState);
    html.classList.add('is-3d');
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      bottle3d = null;
      html.classList.remove('is-3d');
      dirty = true;
    });
  } catch (err) {
    // WebGL missing or blocked: the flat bottle keeps following the timeline.
    console.info('[drip] 3D bottle unavailable, using the flat version.', err);
  }
}

function start() {
  const { gsap, ScrollTrigger } = window;
  if (!gsap || !ScrollTrigger) {
    html.classList.remove('is-cinematic');
    return;
  }
  gsap.registerPlugin(ScrollTrigger);
  ScrollTrigger.config({ ignoreMobileResize: true });

  const mm = gsap.matchMedia();
  mm.add(
    {
      wide: '(min-aspect-ratio: 1/1)',
      // Handlers only run while at least one condition matches, so portrait
      // needs its own entry even though it's just "not wide".
      tall: '(max-aspect-ratio: 1/1)',
      reduce: '(prefers-reduced-motion: reduce)',
    },
    (ctx) => {
      const { wide, reduce } = ctx.conditions;
      if (reduce) {
        html.classList.remove('is-cinematic');
        return undefined;
      }
      html.classList.add('is-cinematic');
      measure();
      buildTimeline({ gsap, root: document, wide, bottleState, shapeState, onChange: () => { dirty = true; } });
      if (!bottle3d && !load3D.started) {
        load3D.started = true;
        // Let the first paint and fonts land before parsing three.js.
        (window.requestIdleCallback || ((f) => setTimeout(f, 60)))(load3D, { timeout: 600 });
      }
      dirty = true;
      return () => html.classList.remove('is-cinematic');
    },
  );

  gsap.ticker.add(frame);
  new ResizeObserver(measure).observe(stage);
  // Fonts change text metrics; recompute trigger positions once they're in.
  document.fonts?.ready.then(() => ScrollTrigger.refresh());
}

start();
