// Response cache sized for strict free-tier quotas. Entries stay on disk so a
// restart does not spend requests again, and expired entries are kept as a
// clearly-marked stale fallback when the provider fails.
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export class MarketCache {
  constructor({ file = null, now = () => Date.now() } = {}) {
    this.file = file;
    this.now = now;
    this.entries = {};
    this.meta = {};
    this.inflight = new Map();
    if (file && existsSync(file)) {
      try {
        const saved = JSON.parse(readFileSync(file, 'utf8'));
        this.entries = saved.entries ?? {};
        this.meta = saved.meta ?? {};
      } catch { /* a corrupt cache file is ignored and rewritten */ }
    }
  }

  persist() {
    if (!this.file) return;
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      const tmp = `${this.file}.tmp`;
      writeFileSync(tmp, JSON.stringify({ entries: this.entries, meta: this.meta }));
      renameSync(tmp, this.file);
    } catch { /* caching is best effort */ }
  }

  peek(key) {
    return this.entries[key];
  }

  set(key, value) {
    this.entries[key] = { value, storedAt: this.now() };
    this.persist();
  }

  // Returns { value, storedAt, fromCache, stale, error }. Throws only when
  // there is no usable copy at all.
  async getOrFetch(key, { ttlMs, maxStaleMs = 0, fetcher, fallbackOn = () => true }) {
    const entry = this.entries[key];
    const age = entry ? this.now() - entry.storedAt : Infinity;
    if (entry && age < ttlMs) return { ...entry, fromCache: true, stale: false, error: null };

    if (!this.inflight.has(key)) {
      const p = (async () => {
        const value = await fetcher();
        this.set(key, value);
        return this.entries[key];
      })().finally(() => this.inflight.delete(key));
      this.inflight.set(key, p);
    }
    try {
      const fresh = await this.inflight.get(key);
      return { ...fresh, fromCache: false, stale: false, error: null };
    } catch (error) {
      if (entry && age < ttlMs + maxStaleMs && fallbackOn(error)) {
        return { ...entry, fromCache: true, stale: true, error };
      }
      throw error;
    }
  }
}
