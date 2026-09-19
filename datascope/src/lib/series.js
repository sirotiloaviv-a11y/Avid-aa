/**
 * The rolling intraday series behind the chart and the alert engine.
 *
 * Two different providers feed this: Binance sends finished 1-minute candles,
 * Finnhub sends individual trades. Both end up here, which means the series has
 * to accept either and produce the same thing - a bounded list of candles plus
 * the latest price.
 *
 * Bounded is the operative word. A dashboard left open all day on a busy pair
 * receives hundreds of thousands of trades; nothing here is allowed to grow with
 * that. Trades are folded into fixed buckets on arrival and old buckets are
 * dropped, so memory is a function of the window, not of uptime.
 */

/** One minute buckets, four hours of history: 240 candles per asset. */
export const DEFAULT_BUCKET_MS = 60_000;
export const DEFAULT_CAPACITY = 240;

export class Series {
  /**
   * @param {{bucketMs?: number, capacity?: number}} [options]
   */
  constructor(options = {}) {
    this.bucketMs = options.bucketMs ?? DEFAULT_BUCKET_MS;
    this.capacity = options.capacity ?? DEFAULT_CAPACITY;
    /** @type {import('./model.js').Candle[]} Ascending by time. */
    this.candles = [];
    /** @type {number|null} */
    this.lastPrice = null;
    /** @type {number|null} */
    this.lastUpdateAt = null;
  }

  /** @param {number} ts */
  bucketStart(ts) {
    return Math.floor(ts / this.bucketMs) * this.bucketMs;
  }

  /**
   * Folds one trade into its bucket, opening a new candle when the bucket rolls.
   * @param {number} price
   * @param {number} size
   * @param {number} ts
   */
  addTrade(price, size, ts) {
    if (!Number.isFinite(price)) return;
    const t = this.bucketStart(ts);
    const last = this.candles[this.candles.length - 1];

    if (last && last.t === t) {
      last.close = price;
      if (price > last.high) last.high = price;
      if (price < last.low) last.low = price;
      last.volume += Number.isFinite(size) ? size : 0;
    } else if (last && t < last.t) {
      // Out-of-order trade from an earlier bucket: fold it in if that bucket is
      // still in the window, otherwise drop it. Never append out of order - the
      // chart and every window query assume ascending time.
      const target = this.candles.find((candle) => candle.t === t);
      if (target) {
        if (price > target.high) target.high = price;
        if (price < target.low) target.low = price;
        target.volume += Number.isFinite(size) ? size : 0;
      }
      return;
    } else {
      this.candles.push({
        t,
        open: price,
        high: price,
        low: price,
        close: price,
        volume: Number.isFinite(size) ? size : 0,
      });
      this.trim();
    }

    this.lastPrice = price;
    this.lastUpdateAt = ts;
  }

  /**
   * Applies a candle from a provider that sends them directly.
   * An open candle is revised in place; a closed one is final.
   * @param {import('./model.js').Candle} candle
   */
  applyCandle(candle) {
    if (!candle || !Number.isFinite(candle.close)) return;
    const t = this.bucketStart(candle.t);
    const index = this.candles.findIndex((entry) => entry.t === t);
    const next = { ...candle, t };

    if (index === -1) {
      // Keep ascending order even if a late candle arrives after a newer one.
      const position = this.candles.findIndex((entry) => entry.t > t);
      if (position === -1) this.candles.push(next);
      else this.candles.splice(position, 0, next);
      this.trim();
    } else {
      this.candles[index] = next;
    }

    const newest = this.candles[this.candles.length - 1];
    if (newest && newest.t === t) {
      this.lastPrice = candle.close;
      this.lastUpdateAt = Math.max(this.lastUpdateAt ?? 0, candle.t);
    }
  }

  /**
   * Replaces the whole history, e.g. when seeding from a REST backfill.
   * @param {import('./model.js').Candle[]} candles
   */
  seed(candles) {
    if (!Array.isArray(candles) || candles.length === 0) return;
    const sorted = candles
      .filter((candle) => candle && Number.isFinite(candle.t) && Number.isFinite(candle.close))
      .slice()
      .sort((a, b) => a.t - b.t)
      .map((candle) => ({ ...candle, t: this.bucketStart(candle.t) }));
    this.candles = sorted.slice(-this.capacity);
    const last = this.candles[this.candles.length - 1];
    if (last) {
      this.lastPrice = last.close;
      this.lastUpdateAt = last.t;
    }
  }

  trim() {
    if (this.candles.length > this.capacity) {
      this.candles.splice(0, this.candles.length - this.capacity);
    }
  }

  /** @returns {import('./model.js').Candle[]} */
  window(fromTs, toTs = Number.POSITIVE_INFINITY) {
    return this.candles.filter((candle) => candle.t >= fromTs && candle.t <= toTs);
  }

  /**
   * The close at or immediately before `ts` - the reference point for a
   * "% change over the last N minutes" rule.
   * @param {number} ts
   * @returns {number|null}
   */
  priceAt(ts) {
    let found = null;
    for (const candle of this.candles) {
      if (candle.t <= ts) found = candle.close;
      else break;
    }
    return found;
  }

  /**
   * Volume traded since `ts`.
   * @param {number} ts
   */
  volumeSince(ts) {
    let total = 0;
    for (const candle of this.candles) {
      if (candle.t >= ts) total += candle.volume;
    }
    return total;
  }

  /**
   * Mean volume per bucket over [fromTs, toTs) - the baseline a volume-surge
   * rule compares against.
   * @returns {number|null} Null when the range holds no buckets at all, so a
   *   rule cannot divide by an empty history.
   */
  averageVolume(fromTs, toTs) {
    let total = 0;
    let count = 0;
    for (const candle of this.candles) {
      if (candle.t >= fromTs && candle.t < toTs) {
        total += candle.volume;
        count += 1;
      }
    }
    return count === 0 ? null : total / count;
  }

  /** Session statistics over everything currently held. */
  summary() {
    if (this.candles.length === 0) {
      return { open: null, high: null, low: null, close: null, volume: 0, count: 0 };
    }
    let high = this.candles[0].high;
    let low = this.candles[0].low;
    let volume = 0;
    for (const candle of this.candles) {
      if (candle.high > high) high = candle.high;
      if (candle.low < low) low = candle.low;
      volume += candle.volume;
    }
    return {
      open: this.candles[0].open,
      high,
      low,
      close: this.candles[this.candles.length - 1].close,
      volume,
      count: this.candles.length,
    };
  }

  get length() {
    return this.candles.length;
  }
}

/**
 * One Series per asset, created on demand.
 */
export class SeriesStore {
  constructor(options = {}) {
    this.options = options;
    /** @type {Map<string, Series>} */
    this.map = new Map();
  }

  /** @param {string} key */
  get(key) {
    let series = this.map.get(key);
    if (!series) {
      series = new Series(this.options);
      this.map.set(key, series);
    }
    return series;
  }

  /** @param {string} key */
  peek(key) {
    return this.map.get(key) ?? null;
  }

  /** @param {string} key */
  delete(key) {
    this.map.delete(key);
  }

  clear() {
    this.map.clear();
  }
}
