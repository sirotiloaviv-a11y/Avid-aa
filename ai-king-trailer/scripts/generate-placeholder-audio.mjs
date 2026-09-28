#!/usr/bin/env node
/**
 * Synthesises placeholder trailer audio into public/audio/ so the project
 * renders with sound out of the box. Pure Node, no dependencies.
 *
 * Existing files are never overwritten — drop your licensed music / SFX in
 * with the same names and this script leaves them alone. Pass --force to
 * regenerate everything.
 */
import {existsSync, mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'audio');
const SR = 22050;
const FORCE = process.argv.includes('--force');
const TAU = Math.PI * 2;

// Deterministic PRNG so every install produces identical files.
let seed = 1337;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296) * 2 - 1;

const buffer = (seconds) => new Float32Array(Math.round(seconds * SR));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/** Mix `src` into `dst` at time `at` (seconds) with gain. */
const mix = (dst, src, at = 0, gain = 1) => {
  const o = Math.round(at * SR);
  for (let i = 0; i < src.length && o + i < dst.length; i++) if (o + i >= 0) dst[o + i] += src[i] * gain;
};

/** One-pole low-pass, cutoff may be a function of time (s). */
const lowpass = (buf, cutoff) => {
  let y = 0;
  for (let i = 0; i < buf.length; i++) {
    const fc = typeof cutoff === 'function' ? cutoff(i / SR) : cutoff;
    const a = 1 - Math.exp((-TAU * fc) / SR);
    y += a * (buf[i] - y);
    buf[i] = y;
  }
  return buf;
};

const highpass = (buf, cutoff) => {
  const low = lowpass(Float32Array.from(buf), cutoff);
  for (let i = 0; i < buf.length; i++) buf[i] -= low[i];
  return buf;
};

/** Oscillator with a frequency function (Hz) and an amplitude envelope. */
const osc = (seconds, freq, env, shape = 'sine') => {
  const b = buffer(seconds);
  let ph = 0;
  for (let i = 0; i < b.length; i++) {
    const t = i / SR;
    ph += (typeof freq === 'function' ? freq(t) : freq) / SR;
    const p = ph % 1;
    let v;
    if (shape === 'saw') v = 2 * p - 1;
    else if (shape === 'square') v = p < 0.5 ? 1 : -1;
    else v = Math.sin(TAU * p);
    b[i] = v * env(t);
  }
  return b;
};

const noise = (seconds, env) => {
  const b = buffer(seconds);
  for (let i = 0; i < b.length; i++) b[i] = rnd() * env(i / SR);
  return b;
};

const expDecay = (k) => (t) => Math.exp(-t * k);
const adsr = (a, d, total) => (t) => (t < a ? t / a : t > total - d ? Math.max(0, (total - t) / d) : 1);

const normalize = (buf, peak = 0.9) => {
  let m = 0;
  for (const v of buf) m = Math.max(m, Math.abs(v));
  if (m > 0) for (let i = 0; i < buf.length; i++) buf[i] = (buf[i] / m) * peak;
  return buf;
};

/** Soft saturation for weight. */
const drive = (buf, amount = 2) => {
  for (let i = 0; i < buf.length; i++) buf[i] = Math.tanh(buf[i] * amount);
  return buf;
};

const writeWav = (name, data) => {
  const path = join(OUT, name);
  if (existsSync(path) && !FORCE) {
    console.log(`  keep   ${name} (already exists)`);
    return;
  }
  const bytes = Buffer.alloc(44 + data.length * 2);
  bytes.write('RIFF', 0);
  bytes.writeUInt32LE(36 + data.length * 2, 4);
  bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20); // PCM
  bytes.writeUInt16LE(1, 22); // mono
  bytes.writeUInt32LE(SR, 24);
  bytes.writeUInt32LE(SR * 2, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36);
  bytes.writeUInt32LE(data.length * 2, 40);
  for (let i = 0; i < data.length; i++) bytes.writeInt16LE(Math.round(clamp(data[i], -1, 1) * 32767), 44 + i * 2);
  writeFileSync(path, bytes);
  console.log(`  write  ${name} (${(bytes.length / 1024).toFixed(0)} KB)`);
};

// ─── Building blocks ────────────────────────────────────────────────────
const kick = () => osc(0.45, (t) => 45 + 110 * Math.exp(-t * 28), expDecay(9));
const snare = () => {
  const n = highpass(noise(0.25, expDecay(18)), 1200);
  mix(n, osc(0.25, 190, expDecay(25)), 0, 0.6);
  return n;
};
const hat = () => highpass(noise(0.06, expDecay(70)), 5000);

const makeBraam = (seconds = 3.2) => {
  const env = (t) => Math.min(1, t / 0.06) * Math.exp(-t * 0.8);
  const b = buffer(seconds);
  for (const [f, g] of [[55, 1], [55.4, 0.8], [82.4, 0.6], [110, 0.4], [27.5, 0.7]]) mix(b, osc(seconds, f, env, 'saw'), 0, g);
  lowpass(b, (t) => 180 + 900 * Math.exp(-t * 2.5));
  return normalize(drive(b, 2.2), 0.95);
};

const makeImpact = () => {
  const b = osc(2, (t) => 38 + 90 * Math.exp(-t * 12), expDecay(2.4));
  mix(b, lowpass(noise(2, expDecay(5)), 900), 0, 0.8);
  mix(b, highpass(noise(0.12, expDecay(40)), 2000), 0, 0.5);
  return normalize(drive(b, 2.5), 0.95);
};

const makeRiser = (seconds = 4) => {
  const env = (t) => (t / seconds) ** 2;
  const b = lowpass(noise(seconds, env), (t) => 300 + 7000 * (t / seconds) ** 2);
  mix(b, osc(seconds, (t) => 200 + 1600 * (t / seconds) ** 2, env, 'saw'), 0, 0.25);
  mix(b, osc(seconds, (t) => 60 + 60 * (t / seconds), env, 'sine'), 0, 0.5);
  return normalize(b, 0.9);
};

const makeWhoosh = () => {
  const d = 0.9;
  const b = noise(d, (t) => Math.sin(Math.PI * clamp(t / d, 0, 1)) ** 2);
  return normalize(lowpass(b, (t) => 400 + 5000 * Math.sin(Math.PI * clamp(t / d, 0, 1))), 0.9);
};

const makeGlitch = () => {
  const d = 0.35;
  const b = buffer(d);
  for (let s = 0; s < 6; s++) {
    const at = (s / 6) * d;
    const f = 300 + Math.abs(rnd()) * 3000;
    mix(b, osc(0.05, f, () => 0.6, 'square'), at);
    mix(b, noise(0.03, () => 0.5), at + 0.02);
  }
  return normalize(b, 0.8);
};

const makeExplosion = () => {
  const d = 3.5;
  const b = lowpass(noise(d, (t) => Math.min(1, t / 0.01) * Math.exp(-t * 1.3)), (t) => 200 + 3000 * Math.exp(-t * 3));
  mix(b, makeImpact(), 0, 0.8);
  // debris crackle
  for (let i = 0; i < 40; i++) mix(b, highpass(noise(0.02, expDecay(90)), 3000), 0.2 + Math.abs(rnd()) * 2.5, 0.3);
  return normalize(drive(b, 1.8), 0.95);
};

const makeSiren = () => normalize(lowpass(osc(4, (t) => 750 + 350 * Math.sin(TAU * t * 0.9), () => 0.5, 'square'), 2500), 0.6);

const makeTinnitus = () => normalize(osc(3, 4200, (t) => Math.min(1, t / 0.05) * Math.exp(-t * 1.1)), 0.5);

const makeHeartbeat = () => {
  const b = buffer(1.0); // 60 bpm, loops
  const thump = () => osc(0.25, (t) => 40 + 30 * Math.exp(-t * 30), expDecay(14));
  mix(b, thump(), 0, 1);
  mix(b, thump(), 0.22, 0.7);
  return normalize(b, 0.95);
};

const makeRain = () => {
  const d = 8;
  const b = lowpass(noise(d, () => 0.6), 3500);
  highpass(b, 400);
  for (let i = 0; i < 900; i++) mix(b, highpass(noise(0.01, expDecay(300)), 2500), Math.abs(rnd()) * d, 0.35);
  // crossfade tail into head so it loops cleanly
  const x = Math.round(0.5 * SR);
  for (let i = 0; i < x; i++) {
    const g = i / x;
    b[i] = b[i] * g + b[b.length - x + i] * (1 - g);
  }
  return normalize(b.subarray(0, b.length - x), 0.7);
};

/**
 * 60-second score that follows the four acts:
 *   0–10s  drone + pulse, 10–25s tension pad + clock ticks,
 *   25–50s 140bpm action (drops out 46.3–48s), 50–60s hits + final chord.
 */
const makeScore = () => {
  const total = 60;
  const b = buffer(total);

  // ACT I — low drone, slowly opening filter
  const drone = osc(25, 55, adsr(3, 2, 25), 'saw');
  mix(drone, osc(25, 82.4, adsr(3, 2, 25), 'saw'), 0, 0.5);
  mix(b, lowpass(drone, (t) => 120 + t * 25), 0, 0.5);
  for (let t = 0; t < 10; t += 1) mix(b, osc(0.5, 55, expDecay(6)), t, 0.6); // slow pulse

  // ACT II — minor pad swell + ticking clock
  const pad = buffer(15);
  for (const f of [110, 130.81, 164.81, 220]) mix(pad, osc(15, f, adsr(4, 1.5, 15)), 0, 0.25);
  mix(b, lowpass(pad, 1400), 10, 0.8);
  for (let t = 10; t < 25; t += 0.5) mix(b, hat(), t, 0.5);

  // ACT III — 140 bpm action
  const beat = 60 / 140;
  const bassNotes = [55, 55, 65.4, 55, 49, 55, 73.4, 65.4];
  for (let t = 25, n = 0; t < 46.3; t += beat / 2, n++) {
    mix(b, lowpass(osc(beat / 2, bassNotes[n % 8], expDecay(5), 'saw'), 500), t, 0.45); // 8th-note ostinato
    if (n % 2 === 0) mix(b, kick(), t, 0.9);
    if (n % 4 === 2) mix(b, snare(), t, 0.55);
    mix(b, hat(), t, 0.25);
    if (n % 16 === 0) mix(b, makeBraam(2), t, 0.5);
  }
  // 46.3–48s: silence (only a sub-drone) — then 48–50s riser is an SFX
  mix(b, osc(3.7, 36, adsr(0.5, 1, 3.7)), 46.3, 0.35);

  // ACT IV — title hits + resolving chord
  mix(b, makeBraam(4), 50.2, 0.9);
  const chord = buffer(9.5);
  for (const f of [55, 110, 164.81, 220, 261.63, 329.63]) mix(chord, osc(9.5, f, adsr(0.05, 3, 9.5), 'saw'), 0, 0.18);
  mix(b, lowpass(chord, (t) => 2500 * Math.exp(-t * 0.35) + 200), 50.3, 0.7);

  return normalize(drive(b, 1.4), 0.85);
};

// ─── Write everything ───────────────────────────────────────────────────
mkdirSync(OUT, {recursive: true});
console.log('Generating placeholder trailer audio → public/audio/');
writeWav('score.wav', makeScore());
writeWav('rain.wav', makeRain());
writeWav('glitch.wav', makeGlitch());
writeWav('riser.wav', makeRiser());
writeWav('braam.wav', makeBraam());
writeWav('impact.wav', makeImpact());
writeWav('whoosh.wav', makeWhoosh());
writeWav('siren.wav', makeSiren());
writeWav('tinnitus.wav', makeTinnitus());
writeWav('heartbeat.wav', makeHeartbeat());
writeWav('explosion.wav', makeExplosion());
console.log('Done. Replace any file with licensed audio of the same name to upgrade the mix.');
