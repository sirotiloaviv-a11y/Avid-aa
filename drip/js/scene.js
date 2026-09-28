// Scroll-driven product story. One GSAP timeline, scrubbed by ScrollTrigger,
// drives three things as a single scene: the bottle state, the black shape
// and the text beats. Scrolling back up plays the same timeline in reverse.
//
// Positions are fractions of the stage: x/y is the bottle's centre, h is its
// height relative to the stage height. The shape is a four-corner polygon
// (TL, TR, BR, BL) with a corner radius in px.

const WIDE = {
  bottle: {
    hero: { x: 0.665, y: 0.56, h: 1.22, tilt: -24, spin: -38, lean: 10, shadow: 0 },
    uvc: { x: 0.5, y: 0.39, h: 0.56, tilt: 0, spin: 0, lean: 4, shadow: 0 },
    f1: { x: 0.28, y: 0.5, h: 0.7, tilt: -6, spin: 70, lean: 26, shadow: 0 },
    f2: { x: 0.28, y: 0.52, h: 0.8, tilt: 8, spin: 165, lean: 2, shadow: 0 },
    f3: { x: 0.28, y: 0.52, h: 0.8, tilt: 0, spin: 360, lean: 3, shadow: 0 },
    buy: { x: 0.3, y: 0.52, h: 0.76, tilt: 0, spin: 360, lean: 3, shadow: 1 },
  },
  shape: {
    hero: [[0.64, -0.02], [1.02, -0.02], [1.02, 1.02], [0.47, 1.02], 0],
    uvc: [[-0.02, 0.7], [1.02, 0.64], [1.02, 1.02], [-0.02, 1.02], 0],
    features: [[0.54, -0.02], [1.02, -0.02], [1.02, 1.02], [0.47, 1.02], 0],
    buy: [[0.56, 0.12], [0.95, 0.12], [0.95, 0.88], [0.56, 0.88], 28],
  },
};

const TALL = {
  bottle: {
    hero: { x: 0.6, y: 0.8, h: 0.7, tilt: -22, spin: -38, lean: 10, shadow: 0 },
    uvc: { x: 0.5, y: 0.575, h: 0.5, tilt: 0, spin: 0, lean: 4, shadow: 0 },
    f1: { x: 0.5, y: 0.335, h: 0.38, tilt: -6, spin: 70, lean: 26, shadow: 0 },
    f2: { x: 0.5, y: 0.335, h: 0.44, tilt: 8, spin: 165, lean: 2, shadow: 0 },
    f3: { x: 0.5, y: 0.335, h: 0.44, tilt: 0, spin: 360, lean: 3, shadow: 0 },
    buy: { x: 0.5, y: 0.315, h: 0.43, tilt: 0, spin: 360, lean: 3, shadow: 1 },
  },
  shape: {
    hero: [[0.5, 0.6], [1.02, 0.5], [1.02, 1.02], [0.12, 1.02], 0],
    uvc: [[-0.02, 0.84], [1.02, 0.78], [1.02, 1.02], [-0.02, 1.02], 0],
    features: [[-0.02, 0.62], [1.02, 0.57], [1.02, 1.02], [-0.02, 1.02], 0],
    buy: [[0.04, 0.585], [0.96, 0.585], [0.96, 0.965], [0.04, 0.965], 24],
  },
};

const flatShape = ([a, b, c, d, r]) => ({ ax: a[0], ay: a[1], bx: b[0], by: b[1], cx: c[0], cy: c[1], dx: d[0], dy: d[1], r });

export function roundedPolygon(pts, radius) {
  let d = '';
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const [px, py] = pts[(i + n - 1) % n];
    const [x, y] = pts[i];
    const [nx, ny] = pts[(i + 1) % n];
    const l1 = Math.hypot(px - x, py - y) || 1;
    const l2 = Math.hypot(nx - x, ny - y) || 1;
    const r = Math.max(0, Math.min(radius, l1 / 2, l2 / 2));
    const x1 = x + ((px - x) / l1) * r;
    const y1 = y + ((py - y) / l1) * r;
    const x2 = x + ((nx - x) / l2) * r;
    const y2 = y + ((ny - y) / l2) * r;
    d += `${i ? 'L' : 'M'}${x1.toFixed(1)} ${y1.toFixed(1)}Q${x.toFixed(1)} ${y.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  return `${d}Z`;
}

/**
 * Builds the timeline for one layout. Must run inside a gsap.matchMedia()
 * handler so every tween and inline style is reverted on layout change.
 */
export function buildTimeline({ gsap, root, wide, bottleState, shapeState, onChange }) {
  const K = wide ? WIDE : TALL;
  const q = (s) => root.querySelector(s);
  const beats = {
    hero: q('[data-beat="hero"]'),
    uvc: q('[data-beat="uvc"]'),
    features: q('[data-beat="features"]'),
    buy: q('[data-beat="buy"]'),
  };
  const features = [...root.querySelectorAll('[data-feature]')];
  const lines = (el) => el.querySelectorAll('.ln-i');

  // Initial state = the first frame of the story.
  Object.assign(bottleState, K.bottle.hero);
  Object.assign(shapeState, flatShape(K.shape.hero));
  gsap.set([beats.uvc, beats.features, beats.buy, ...features], { autoAlpha: 0 });
  gsap.set(beats.hero, { autoAlpha: 1 });
  gsap.set([lines(beats.uvc), ...features.map(lines)], { yPercent: 110 });
  gsap.set(lines(beats.hero), { yPercent: 0 });
  gsap.set(beats.buy.children, { autoAlpha: 0, y: 28 });

  const tl = gsap.timeline({
    defaults: { ease: 'none', immediateRender: false },
    onUpdate: onChange,
    scrollTrigger: {
      trigger: q('[data-experience]') || root,
      start: 'top top',
      end: 'bottom bottom',
      scrub: 0.6,
    },
  });

  const bottle = (from, to, at, dur) =>
    tl.fromTo(bottleState, { ...K.bottle[from] }, { ...K.bottle[to], duration: dur, ease: 'power2.inOut' }, at);
  const shape = (from, to, at, dur) =>
    tl.fromTo(shapeState, flatShape(K.shape[from]), { ...flatShape(K.shape[to]), duration: dur, ease: 'power2.inOut' }, at);

  const show = (el, at) => tl.fromTo(el, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.001 }, at);
  const hide = (el, at) => tl.fromTo(el, { autoAlpha: 1 }, { autoAlpha: 0, duration: 0.001 }, at);
  const linesIn = (el, at, dur) => {
    show(el, at);
    const l = lines(el);
    tl.fromTo(l, { yPercent: 110 }, { yPercent: 0, duration: dur, ease: 'power3.out', stagger: (dur * 0.35) / Math.max(1, l.length - 1) }, at);
  };
  const linesOut = (el, at, dur) => {
    const l = lines(el);
    tl.fromTo(l, { yPercent: 0 }, { yPercent: -110, duration: dur, ease: 'power2.in', stagger: (dur * 0.25) / Math.max(1, l.length - 1) }, at);
    hide(el, at + dur * 1.25);
  };

  // Act 1 — close-up to centre, headline hands over to "UV-C Water Bottle".
  linesOut(beats.hero, 0.15, 0.6);
  bottle('hero', 'uvc', 0.1, 2.2);
  shape('hero', 'uvc', 0.5, 1.4);
  linesIn(beats.uvc, 1.8, 0.8);

  // Act 2 — bottle moves aside, details reveal one at a time on the black side.
  linesOut(beats.uvc, 3.3, 0.5);
  bottle('uvc', 'f1', 3.5, 1.5);
  shape('uvc', 'features', 3.7, 1.2);
  show(beats.features, 4.8);
  linesIn(features[0], 4.8, 0.5);
  linesOut(features[0], 5.9, 0.3);
  bottle('f1', 'f2', 5.9, 0.9);
  linesIn(features[1], 6.4, 0.5);
  linesOut(features[1], 7.4, 0.3);
  bottle('f2', 'f3', 7.4, 0.8);
  linesIn(features[2], 7.8, 0.5);

  // Act 3 — the full bottle stands next to colour selection and the CTA.
  linesOut(features[2], 8.7, 0.3);
  hide(beats.features, 9.1);
  bottle('f3', 'buy', 8.8, 0.8);
  shape('features', 'buy', 8.8, 0.8);
  show(beats.buy, 9.3);
  tl.fromTo(beats.buy.children, { autoAlpha: 0, y: 28 }, { autoAlpha: 1, y: 0, duration: 0.5, stagger: 0.05, ease: 'power3.out' }, 9.3);

  // Hold the final composition before the stage releases.
  const rail = q('[data-rail]');
  tl.fromTo(rail, { scaleX: 0 }, { scaleX: 1, duration: 10.4 }, 0);

  return tl;
}
