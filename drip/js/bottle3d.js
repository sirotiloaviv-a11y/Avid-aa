// Procedural DRIP bottle rendered with three.js.
// The scene is laid out in viewport terms: the scroll timeline hands us the
// bottle's centre (x, y as fractions of the stage), its height as a fraction
// of the stage height, and three rotations. That keeps the 3D object and the
// HTML typography on one shared grid.
import * as THREE from '../vendor/three.module.min.js';
import { RoomEnvironment } from '../vendor/RoomEnvironment.js';
import { MARK_PATH, MARK_W, MARK_H } from './brand.js';

const R = 0.155; // body radius; the bottle is 1 unit tall, centred on the origin
const BODY_TOP = 0.305;
const CAP_BOTTOM = 0.323;
const LABEL_H = 0.3;
const LABEL_Y = -0.02;
const FOV = 18;
const CAM_Z = 12;
const VIS_H = 2 * CAM_Z * Math.tan(THREE.MathUtils.degToRad(FOV / 2));
const DEG = Math.PI / 180;

function arc(points, cx, cy, r, from, to, steps) {
  for (let i = 0; i <= steps; i++) {
    const a = from + ((to - from) * i) / steps;
    points.push(new THREE.Vector2(cx + r * Math.cos(a), cy + r * Math.sin(a)));
  }
}

function bodyGeometry() {
  const f = 0.035;
  const p = [new THREE.Vector2(0, -0.5)];
  arc(p, R - f, -0.5 + f, f, -Math.PI / 2, 0, 10);
  p.push(new THREE.Vector2(R, BODY_TOP - 0.006));
  p.push(new THREE.Vector2(R - 0.004, BODY_TOP));
  p.push(new THREE.Vector2(0, BODY_TOP));
  return new THREE.LatheGeometry(p, 128);
}

function capGeometry() {
  const f = 0.04;
  const p = [new THREE.Vector2(0, CAP_BOTTOM), new THREE.Vector2(R - 0.004, CAP_BOTTOM), new THREE.Vector2(R, CAP_BOTTOM + 0.006)];
  arc(p, R - f, 0.5 - f, f, 0, Math.PI / 2, 10);
  p.push(new THREE.Vector2(0, 0.5));
  return new THREE.LatheGeometry(p, 128);
}

// White artwork on a transparent canvas; the material colour tints it, so the
// same texture serves light and dark bottle colours.
function labelCanvas(maxAniso) {
  const W = 2048;
  const H = Math.round((W * LABEL_H) / (2 * Math.PI * R));
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff';

  // Front: the wordmark, ~0.3 units wide, centred on u = 0.5 (facing the camera).
  const markPx = (W * 0.3) / (2 * Math.PI * R);
  const s = markPx / MARK_W;
  ctx.save();
  ctx.translate(W / 2 - (MARK_W * s) / 2, H / 2 - (MARK_H * s) / 2);
  ctx.scale(s, s);
  ctx.fill(new Path2D(MARK_PATH), 'evenodd');
  ctx.restore();

  // Back: a small tagline, drawn across the seam at u = 0 / u = 1.
  const size = Math.round(H * 0.075);
  ctx.font = `500 ${size}px Inter, "Helvetica Neue", Arial, sans-serif`;
  if ('letterSpacing' in ctx) ctx.letterSpacing = `${Math.round(size * 0.22)}px`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const x of [0, W]) ctx.fillText('UV-C WATER BOTTLE', x, H / 2);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = maxAniso;
  return tex;
}

function shadowTexture() {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 64;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(128, 32, 0, 128, 32, 128);
  g.addColorStop(0, 'rgba(0,0,0,0.55)');
  g.addColorStop(0.45, 'rgba(0,0,0,0.22)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.setTransform(1, 0, 0, 0.25, 0, 24);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export async function createBottle3D(canvas) {
  // Throws when WebGL is unavailable; the caller keeps the flat bottle then.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, window.innerWidth < 700 ? 2 : 1.75));

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();

  const camera = new THREE.PerspectiveCamera(FOV, 1, 1, 40);
  camera.position.set(0, 0, CAM_Z);

  const key = new THREE.DirectionalLight(0xffffff, 1.3);
  key.position.set(-4, 5, 6);
  const rim = new THREE.DirectionalLight(0xfff6ea, 3.2);
  rim.position.set(5, 2, -3);
  const rim2 = new THREE.DirectionalLight(0xffffff, 1.6);
  rim2.position.set(-5, -1, -2.5);
  scene.add(key, rim, rim2, new THREE.AmbientLight(0xffffff, 0.15));

  // Wait for the brand font so the tagline texture uses it.
  try { await document.fonts.load('500 24px Inter'); } catch { /* fall back to system font */ }

  const bodyMat = new THREE.MeshPhysicalMaterial({
    color: 0x141414, roughness: 0.5, metalness: 0, clearcoat: 0.4, clearcoatRoughness: 0.42, envMapIntensity: 0.42,
  });
  const capMat = new THREE.MeshPhysicalMaterial({
    color: 0x141414, roughness: 0.6, metalness: 0, clearcoat: 0.2, clearcoatRoughness: 0.5, envMapIntensity: 0.38,
  });
  const ringMat = new THREE.MeshStandardMaterial({ color: 0xdadada, metalness: 1, roughness: 0.24, envMapIntensity: 1.2 });
  const labelMat = new THREE.MeshStandardMaterial({
    color: 0xf4f1ea, map: labelCanvas(renderer.capabilities.getMaxAnisotropy()), transparent: true,
    roughness: 0.5, metalness: 0, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2,
  });

  const bottle = new THREE.Group();
  bottle.add(new THREE.Mesh(bodyGeometry(), bodyMat));
  bottle.add(new THREE.Mesh(capGeometry(), capMat));
  const ring = new THREE.Mesh(new THREE.CylinderGeometry(R - 0.002, R - 0.002, CAP_BOTTOM - BODY_TOP, 128, 1, true), ringMat);
  ring.position.y = (BODY_TOP + CAP_BOTTOM) / 2;
  bottle.add(ring);
  const label = new THREE.Mesh(new THREE.CylinderGeometry(R + 0.0012, R + 0.0012, LABEL_H, 160, 1, true, -Math.PI, Math.PI * 2), labelMat);
  label.position.y = LABEL_Y;
  bottle.add(label);
  bottle.rotation.order = 'ZXY'; // spin around the bottle's own axis, then lean, then tilt
  scene.add(bottle);

  const shadowMat = new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false, opacity: 0 });
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 0.25), shadowMat);
  shadow.renderOrder = -1;
  scene.add(shadow);

  const target = { body: new THREE.Color(0x141414), ink: new THREE.Color(0xf4f1ea) };
  let colorAnimating = false;
  let aspect = 1;
  const tmp = new THREE.Vector3();

  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    aspect = w / h;
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
  }

  function stepColor() {
    const k = 0.18;
    bodyMat.color.lerp(target.body, k);
    capMat.color.lerp(target.body, k);
    labelMat.color.lerp(target.ink, k);
    const done = Math.abs(bodyMat.color.r - target.body.r) + Math.abs(bodyMat.color.g - target.body.g) + Math.abs(bodyMat.color.b - target.body.b) < 0.002;
    if (done) {
      bodyMat.color.copy(target.body);
      capMat.color.copy(target.body);
      labelMat.color.copy(target.ink);
    }
    colorAnimating = !done;
  }

  function render(s) {
    if (colorAnimating) stepColor();
    const visW = VIS_H * aspect;
    bottle.position.set((s.x - 0.5) * visW, (0.5 - s.y) * VIS_H, 0);
    bottle.scale.setScalar(s.h * VIS_H);
    bottle.rotation.set(s.lean * DEG, s.spin * DEG, s.tilt * DEG);

    shadowMat.opacity = s.shadow;
    shadow.visible = s.shadow > 0.001;
    if (shadow.visible) {
      bottle.updateMatrixWorld();
      tmp.set(0, -0.5, 0).applyMatrix4(bottle.matrixWorld);
      const size = s.h * VIS_H;
      shadow.position.set(tmp.x, tmp.y - size * 0.004, -0.6);
      shadow.scale.set(size * 0.5, size * 0.5, 1);
    }
    renderer.render(scene, camera);
  }

  // Compile every material up front so the first time the shadow (or any
  // other mesh) appears mid-scroll doesn't stall a frame.
  shadow.visible = true;
  renderer.compile(scene, camera);
  shadow.visible = false;

  return {
    resize,
    render,
    get needsFrame() { return colorAnimating; },
    setColor(body, ink, instant = false) {
      target.body.set(body);
      target.ink.set(ink);
      colorAnimating = true;
      if (instant) {
        bodyMat.color.copy(target.body);
        capMat.color.copy(target.body);
        labelMat.color.copy(target.ink);
        colorAnimating = false;
      }
    },
  };
}
