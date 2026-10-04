'use client';

import { API_URL } from '../config';

// Decides once per page load whether to talk to the real backend ('live') or
// to the in-browser mock ('demo').
//   NEXT_PUBLIC_DEMO_MODE=true|false  forces a mode
//   ?demo=1 / ?demo=0                 forces or clears demo for this tab
//   otherwise                         demo when GET /api/health is unreachable
const FORCED = process.env.NEXT_PUBLIC_DEMO_MODE;
const TAB_KEY = 'wfp_force_demo';
const PROBE_TIMEOUT_MS = 2500;

let mode = null;
let pending = null;

export function currentMode() {
  return mode;
}

export function isDemoMode() {
  return mode === 'demo';
}

export function resolveMode() {
  if (mode) return Promise.resolve(mode);
  if (!pending) {
    pending = detect().then((m) => {
      mode = m;
      return m;
    });
  }
  return pending;
}

function tabForcedDemo() {
  try {
    const param = new URLSearchParams(window.location.search).get('demo');
    if (param === '1' || param === 'true') window.sessionStorage.setItem(TAB_KEY, '1');
    if (param === '0' || param === 'false') window.sessionStorage.removeItem(TAB_KEY);
    return window.sessionStorage.getItem(TAB_KEY) === '1';
  } catch {
    return false;
  }
}

async function detect() {
  if (FORCED === 'true') return 'demo';
  if (FORCED === 'false') return 'live';
  if (typeof window === 'undefined') return 'live';
  if (tabForcedDemo()) return 'demo';

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}/api/health`, { signal: controller.signal, cache: 'no-store' });
    return res.ok ? 'live' : 'demo';
  } catch {
    return 'demo';
  } finally {
    clearTimeout(timer);
  }
}
