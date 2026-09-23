// Client-side request budget, so the app stops before the provider's quota
// does. Counters live in the cache's persisted meta block.
export class RequestBudget {
  constructor({ name, perMinute = Infinity, perDay = Infinity, perMonth = Infinity, cache, now = () => Date.now() }) {
    this.name = name;
    this.limits = { perMinute, perDay, perMonth };
    this.cache = cache;
    this.now = now;
    this.recent = [];
  }

  state() {
    const m = (this.cache.meta.usage ??= {});
    return (m[this.name] ??= { day: '', dayCount: 0, month: '', monthCount: 0, blockedUntil: 0 });
  }

  // UTC calendar is used for day and month windows; providers may reset on
  // a different clock, which is why the limits are configurable.
  roll(s) {
    const iso = new Date(this.now()).toISOString();
    if (s.day !== iso.slice(0, 10)) { s.day = iso.slice(0, 10); s.dayCount = 0; }
    if (s.month !== iso.slice(0, 7)) { s.month = iso.slice(0, 7); s.monthCount = 0; }
  }

  tryConsume() {
    const s = this.state();
    this.roll(s);
    const now = this.now();
    if (s.blockedUntil > now) return { ok: false, retryAfterSec: (s.blockedUntil - now) / 1000, scope: 'provider' };
    this.recent = this.recent.filter((t) => now - t < 60000);
    if (this.recent.length >= this.limits.perMinute) {
      return { ok: false, retryAfterSec: (60000 - (now - this.recent[0])) / 1000, scope: 'minute' };
    }
    if (s.dayCount >= this.limits.perDay) {
      const tomorrow = Date.parse(`${s.day}T00:00:00Z`) + 86400000;
      return { ok: false, retryAfterSec: (tomorrow - now) / 1000, scope: 'day' };
    }
    if (s.monthCount >= this.limits.perMonth) return { ok: false, retryAfterSec: null, scope: 'month' };
    this.recent.push(now);
    s.dayCount++;
    s.monthCount++;
    this.cache.persist();
    return { ok: true };
  }

  blockFor(seconds) {
    this.state().blockedUntil = this.now() + seconds * 1000;
    this.cache.persist();
  }

  snapshot() {
    const s = this.state();
    this.roll(s);
    return { dayCount: s.dayCount, monthCount: s.monthCount, limits: this.limits, blockedUntil: s.blockedUntil || null };
  }
}
