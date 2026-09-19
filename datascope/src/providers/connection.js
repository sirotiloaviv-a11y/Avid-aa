/**
 * Connection management: a reconnecting socket and a polling loop, both
 * reporting the same status vocabulary.
 *
 * Neither class references a global. The WebSocket constructor, the fetch
 * implementation and the clock are all injected, which is what lets the tests
 * drive reconnection, backoff and staleness deterministically instead of waiting
 * on real timers and a real network.
 *
 * Status is what the header pill shows, so it has to be honest: "connected"
 * means the socket is open *and* data has arrived recently. A socket that stays
 * open while the feed goes silent is reported stale, because a frozen price
 * that looks live is the worst failure this dashboard can have.
 */

import { CONNECTION } from '../lib/model.js';

const DEFAULTS = Object.freeze({
  initialBackoffMs: 1_000,
  maxBackoffMs: 30_000,
  backoffFactor: 2,
  /** Data older than this means the feed is silent even if the socket is open. */
  staleAfterMs: 60_000,
});

/**
 * Exponential backoff with full jitter. Jitter matters: without it every open
 * tab reconnects on the same schedule and hammers the provider in lockstep.
 * @param {number} attempt 1-based.
 * @param {{initialBackoffMs: number, maxBackoffMs: number, backoffFactor: number}} options
 * @param {() => number} random
 */
export function backoffDelay(attempt, options, random = Math.random) {
  const raw = options.initialBackoffMs * options.backoffFactor ** Math.max(0, attempt - 1);
  const capped = Math.min(options.maxBackoffMs, raw);
  return Math.round(capped * (0.5 + 0.5 * random()));
}

/**
 * A WebSocket that reconnects, reports status, and reopens on demand.
 *
 * @example
 * const socket = new ReconnectingSocket({
 *   url: () => streamUrl(symbols),
 *   onMessage: (text) => {},
 *   onStatus: (status, detail) => {},
 * });
 * socket.open();
 */
export class ReconnectingSocket {
  /**
   * @param {object} options
   * @param {() => string} options.url Recomputed on every attempt, so a changed
   *   subscription list is picked up without tearing the class down.
   * @param {(text: string) => void} options.onMessage
   * @param {(status: string, detail?: string) => void} [options.onStatus]
   * @param {(socket: any) => void} [options.onOpen] Send subscriptions here.
   * @param {typeof WebSocket} [options.WebSocketImpl]
   * @param {(fn: () => void, ms: number) => any} [options.setTimeoutImpl]
   * @param {(handle: any) => void} [options.clearTimeoutImpl]
   * @param {() => number} [options.now]
   * @param {() => number} [options.random]
   * @param {Partial<typeof DEFAULTS>} [options.tuning]
   */
  constructor(options) {
    this.options = options;
    this.tuning = { ...DEFAULTS, ...(options.tuning ?? {}) };
    // `??` would treat an explicit null as "not supplied"; a caller passing null
    // means "this environment has no WebSocket", which is a different thing.
    this.WebSocketImpl =
      options.WebSocketImpl !== undefined ? options.WebSocketImpl : globalThis.WebSocket;
    this.setTimeoutImpl = options.setTimeoutImpl ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimeoutImpl = options.clearTimeoutImpl ?? ((handle) => clearTimeout(handle));
    this.now = options.now ?? (() => Date.now());
    this.random = options.random ?? Math.random;

    this.socket = null;
    this.status = CONNECTION.IDLE;
    this.attempt = 0;
    this.lastMessageAt = null;
    this.closedByUs = false;
    this.retryHandle = null;
  }

  /** @param {string} status @param {string} [detail] */
  setStatus(status, detail) {
    this.status = status;
    this.options.onStatus?.(status, detail);
  }

  open() {
    this.closedByUs = false;
    this.cancelRetry();

    if (!this.WebSocketImpl) {
      this.setStatus(CONNECTION.ERROR, 'הדפדפן אינו תומך ב־WebSocket');
      return;
    }

    let url;
    try {
      url = this.options.url();
    } catch (error) {
      this.setStatus(CONNECTION.ERROR, describe(error));
      return;
    }

    this.setStatus(this.attempt === 0 ? CONNECTION.CONNECTING : CONNECTION.RECONNECTING);

    let socket;
    try {
      socket = new this.WebSocketImpl(url);
    } catch (error) {
      this.scheduleRetry(describe(error));
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.lastMessageAt = this.now();
      this.setStatus(CONNECTION.CONNECTED);
      this.options.onOpen?.(socket);
    };

    socket.onmessage = (event) => {
      this.lastMessageAt = this.now();
      if (this.status !== CONNECTION.CONNECTED) this.setStatus(CONNECTION.CONNECTED);
      const data = typeof event?.data === 'string' ? event.data : String(event?.data ?? '');
      if (data) this.options.onMessage(data);
    };

    socket.onerror = () => {
      // The browser gives no detail on socket errors by design; onclose follows
      // and carries the retry.
      if (this.status === CONNECTION.CONNECTED) this.setStatus(CONNECTION.ERROR, 'שגיאת תקשורת');
    };

    socket.onclose = (event) => {
      this.socket = null;
      if (this.closedByUs) {
        this.setStatus(CONNECTION.IDLE);
        return;
      }
      const reason = event?.reason || (event?.code ? `code ${event.code}` : undefined);
      this.scheduleRetry(reason);
    };
  }

  /** @param {string} [detail] */
  scheduleRetry(detail) {
    this.attempt += 1;
    const delay = backoffDelay(this.attempt, this.tuning, this.random);
    this.setStatus(
      CONNECTION.RECONNECTING,
      detail ? `${detail} · ניסיון ${this.attempt}` : `ניסיון ${this.attempt}`,
    );
    this.retryHandle = this.setTimeoutImpl(() => {
      this.retryHandle = null;
      this.open();
    }, delay);
    return delay;
  }

  cancelRetry() {
    if (this.retryHandle !== null) {
      this.clearTimeoutImpl(this.retryHandle);
      this.retryHandle = null;
    }
  }

  /** @param {string} text */
  send(text) {
    // readyState 1 is OPEN. Sending on a closing socket throws in some browsers.
    if (this.socket && this.socket.readyState === 1) {
      this.socket.send(text);
      return true;
    }
    return false;
  }

  /** Closes and reopens immediately - used when the subscription list changes. */
  restart() {
    this.attempt = 0;
    const socket = this.socket;
    this.closedByUs = true;
    this.cancelRetry();
    if (socket) {
      socket.onclose = null;
      socket.onmessage = null;
      socket.onerror = null;
      try {
        socket.close();
      } catch {
        /* already gone */
      }
    }
    this.socket = null;
    this.open();
  }

  close() {
    this.closedByUs = true;
    this.cancelRetry();
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        /* already gone */
      }
      this.socket = null;
    }
    this.setStatus(CONNECTION.IDLE);
  }

  /** True when the socket is open but nothing has arrived for too long. */
  isStale() {
    if (this.status !== CONNECTION.CONNECTED || this.lastMessageAt === null) return false;
    return this.now() - this.lastMessageAt > this.tuning.staleAfterMs;
  }

  /** Milliseconds since the last frame, or null if nothing has arrived yet. */
  silenceMs() {
    return this.lastMessageAt === null ? null : this.now() - this.lastMessageAt;
  }
}

/**
 * A polling loop for providers with no stream (Yahoo, CoinGecko).
 *
 * One poll never overlaps the next: a slow response delays the following tick
 * rather than stacking requests, which is what keeps a rate-limited free tier
 * from being hammered when it is already struggling.
 */
export class PollingSource {
  /**
   * @param {object} options
   * @param {() => Promise<void>} options.poll
   * @param {number} options.intervalMs
   * @param {(status: string, detail?: string) => void} [options.onStatus]
   * @param {(fn: () => void, ms: number) => any} [options.setTimeoutImpl]
   * @param {(handle: any) => void} [options.clearTimeoutImpl]
   * @param {Partial<typeof DEFAULTS>} [options.tuning]
   */
  constructor(options) {
    this.options = options;
    this.tuning = { ...DEFAULTS, ...(options.tuning ?? {}) };
    this.setTimeoutImpl = options.setTimeoutImpl ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimeoutImpl = options.clearTimeoutImpl ?? ((handle) => clearTimeout(handle));
    this.handle = null;
    this.running = false;
    this.attempt = 0;
    this.status = CONNECTION.IDLE;
  }

  setStatus(status, detail) {
    this.status = status;
    this.options.onStatus?.(status, detail);
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.setStatus(CONNECTION.CONNECTING);
    this.tick();
  }

  async tick() {
    if (!this.running) return;
    try {
      await this.options.poll();
      this.attempt = 0;
      if (this.status !== CONNECTION.CONNECTED) this.setStatus(CONNECTION.CONNECTED);
    } catch (error) {
      this.attempt += 1;
      this.setStatus(CONNECTION.RECONNECTING, describe(error));
    }
    if (!this.running) return;
    // A failing poll backs off; a healthy one keeps its steady interval.
    const delay =
      this.attempt === 0
        ? this.options.intervalMs
        : Math.max(this.options.intervalMs, backoffDelay(this.attempt, this.tuning));
    this.handle = this.setTimeoutImpl(() => {
      this.handle = null;
      this.tick();
    }, delay);
  }

  stop() {
    this.running = false;
    if (this.handle !== null) {
      this.clearTimeoutImpl(this.handle);
      this.handle = null;
    }
    this.setStatus(CONNECTION.IDLE);
  }
}

function describe(error) {
  if (!error) return 'שגיאה לא מזוהה';
  if (error instanceof Error) return error.message;
  return String(error);
}
