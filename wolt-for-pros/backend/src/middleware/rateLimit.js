// Fixed-window rate limiting.
//
// MemoryStore is per process: fine for one API instance. Behind a load
// balancer, pass `store: new RedisStore(redisClient)` so every instance
// shares the counters.
const { HttpError } = require('./errors');

class MemoryStore {
  constructor({ sweepIntervalMs = 60000 } = {}) {
    this.hits = new Map(); // key -> { count, resetAt }
    this.sweeper = setInterval(() => this.sweep(), sweepIntervalMs);
    if (this.sweeper.unref) this.sweeper.unref();
  }

  async increment(key, windowMs) {
    const now = Date.now();
    let entry = this.hits.get(key);
    if (!entry || entry.resetAt <= now) {
      entry = { count: 0, resetAt: now + windowMs };
      this.hits.set(key, entry);
    }
    entry.count += 1;
    return { count: entry.count, resetAt: entry.resetAt };
  }

  sweep() {
    const now = Date.now();
    for (const [key, entry] of this.hits) if (entry.resetAt <= now) this.hits.delete(key);
  }

  reset() {
    this.hits.clear();
  }
}

// Template for a shared store. Written against the ioredis client API
// (`new Redis(process.env.REDIS_URL)`); adapt the calls for node-redis.
class RedisStore {
  constructor(client, { prefix = 'rl:' } = {}) {
    this.client = client;
    this.prefix = prefix;
  }

  async increment(key, windowMs) {
    const redisKey = this.prefix + key;
    const [[, count], [, ttl]] = await this.client.multi().incr(redisKey).pttl(redisKey).exec();
    let ttlMs = ttl;
    if (ttl < 0) {
      await this.client.pexpire(redisKey, windowMs);
      ttlMs = windowMs;
    }
    return { count, resetAt: Date.now() + ttlMs };
  }
}

const defaultStore = new MemoryStore();

/**
 * @param {object} options
 * @param {string} options.name                 counter namespace
 * @param {number} options.windowMs
 * @param {number} options.max                  requests allowed per window
 * @param {(req: any) => any} [options.key]      client identity (default: IP); falsy skips limiting
 * @param {string | null} [options.message]
 * @param {{ increment(key: string, windowMs: number): Promise<{ count: number, resetAt: number }> }} [options.store]
 * @param {((req: any) => boolean) | null} [options.skip]
 */
function rateLimit({ name, windowMs, max, key = (req) => req.ip, message = null, store = defaultStore, skip = null }) {
  if (!name || !windowMs || !max) throw new Error('rateLimit needs name, windowMs and max');
  return async (req, res, next) => {
    try {
      if (skip && skip(req)) return next();
      const id = key(req);
      if (!id) return next();
      const { count, resetAt } = await store.increment(`${name}:${id}`, windowMs);
      const remaining = Math.max(0, max - count);
      const retryAfterSec = Math.max(1, Math.ceil((resetAt - Date.now()) / 1000));
      res.setHeader('RateLimit-Limit', String(max));
      res.setHeader('RateLimit-Remaining', String(remaining));
      res.setHeader('RateLimit-Reset', String(retryAfterSec));
      if (count > max) {
        res.setHeader('Retry-After', String(retryAfterSec));
        return next(new HttpError(429, message || 'Too many requests. Slow down and try again shortly.', 'RATE_LIMITED', { retryAfterSec }));
      }
      return next();
    } catch (err) {
      // A broken limiter store must not take the API down with it.
      console.error(`[rateLimit:${name}] store error, allowing request`, err.message);
      return next();
    }
  };
}

const MINUTE = 60 * 1000;

// Limits used by the routes. Keyed by IP unless a better key exists.
const limits = {
  api: rateLimit({ name: 'api', windowMs: MINUTE, max: 300 }),
  auth: rateLimit({ name: 'auth', windowMs: 15 * MINUTE, max: 20, message: 'Too many sign-in attempts. Try again in 15 minutes.' }),
  otpPerPhone: rateLimit({
    name: 'otp-phone',
    windowMs: 15 * MINUTE,
    max: 5,
    key: (req) => (req.body && req.body.phone ? String(req.body.phone).replace(/\D/g, '') : null),
    message: 'Too many codes requested for this number. Try again in 15 minutes.',
  }),
  createJob: rateLimit({ name: 'create-job', windowMs: 60 * MINUTE, max: 10, key: (req) => req.user && req.user.id, message: 'You have opened too many requests this hour.' }),
  completeJob: rateLimit({ name: 'complete-job', windowMs: 10 * MINUTE, max: 10, key: (req) => req.user && req.user.id }),
  upload: rateLimit({ name: 'upload', windowMs: 60 * MINUTE, max: 30, key: (req) => req.user && req.user.id, message: 'Too many uploads this hour.' }),
  message: rateLimit({ name: 'message', windowMs: MINUTE, max: 30, key: (req) => req.user && req.user.id, message: 'You are sending messages too fast.' }),
};

module.exports = { rateLimit, MemoryStore, RedisStore, limits, defaultStore };
