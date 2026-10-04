// Deterministic pseudo-randomness for the mock data generators. A seeded
// generator keeps the demo stable across restarts, which matters when the
// same findings must survive a page reload and a rescan must be reproducible.

/** 32-bit FNV-1a hash of a string. */
export function hashString(input) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Short, URL-safe, stable identifier derived from the given parts. */
export function stableId(prefix, ...parts) {
  return `${prefix}_${hashString(parts.join('|')).toString(36)}`;
}

/** mulberry32: small, fast, good enough for simulated data. */
export function createRng(seed) {
  let state = typeof seed === 'string' ? hashString(seed) : seed >>> 0;

  const next = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  const int = (min, max) => min + Math.floor(next() * (max - min + 1));
  const pick = (items) => items[Math.floor(next() * items.length)];
  const chance = (probability) => next() < probability;

  const sample = (items, count) => {
    const pool = [...items];
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(next() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    return pool.slice(0, Math.min(count, pool.length));
  };

  const hex = (length) => {
    let out = '';
    while (out.length < length) out += Math.floor(next() * 16).toString(16);
    return out;
  };

  const alnum = (length, alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') => {
    let out = '';
    for (let i = 0; i < length; i++) out += alphabet[Math.floor(next() * alphabet.length)];
    return out;
  };

  return { next, int, pick, chance, sample, hex, alnum };
}
