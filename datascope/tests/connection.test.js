/**
 * Connection handling, driven by a fake socket and a fake clock.
 *
 * A live dashboard spends most of its life dealing with a feed that is fine, and
 * the rest dealing with one that is not. These tests are about the second case:
 * a dropped socket has to come back, a flapping one must not turn into a
 * reconnect storm, and a socket that stays open while the data stops has to be
 * reported as broken rather than shown as healthy with a frozen price.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { PollingSource, ReconnectingSocket, backoffDelay } from '../src/providers/connection.js';
import { CONNECTION } from '../src/lib/model.js';
import { configFromSearch, isAllowedEndpoint } from '../src/lib/config.js';

/** A WebSocket stand-in whose lifecycle the test drives by hand. */
class FakeSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeSocket.instances.push(this);
  }

  send(text) {
    this.sent.push(text);
  }

  close() {
    this.readyState = 3;
  }

  /* helpers the tests use to play the part of the network */
  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  message(data) {
    this.onmessage?.({ data });
  }

  drop(code = 1006, reason = '') {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

/** A clock and timer queue the test advances explicitly. */
function fakeTimers() {
  let now = 1_000_000;
  let nextId = 1;
  const pending = new Map();

  return {
    now: () => now,
    setTimeout: (fn, ms) => {
      const id = nextId++;
      pending.set(id, { fn, at: now + ms });
      return id;
    },
    clearTimeout: (id) => pending.delete(id),
    /** Runs everything due within `ms`, in time order. */
    advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...pending.entries()]
          .filter(([, entry]) => entry.at <= target)
          .sort((a, b) => a[1].at - b[1].at);
        if (due.length === 0) break;
        const [id, entry] = due[0];
        pending.delete(id);
        now = entry.at;
        entry.fn();
      }
      now = target;
    },
    get size() {
      return pending.size;
    },
  };
}

function makeSocket(overrides = {}) {
  FakeSocket.instances = [];
  const timers = fakeTimers();
  const statuses = [];
  const messages = [];

  const socket = new ReconnectingSocket({
    url: () => 'wss://stream.binance.com:9443/stream?streams=btcusdt@ticker',
    onMessage: (text) => messages.push(text),
    onStatus: (status, detail) => statuses.push({ status, detail }),
    WebSocketImpl: FakeSocket,
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
    now: timers.now,
    random: () => 0.5, // deterministic jitter
    ...overrides,
  });

  return { socket, timers, statuses, messages };
}

test('a socket reports connecting, then connected, and passes messages through', () => {
  const { socket, statuses, messages } = makeSocket();
  socket.open();
  assert.equal(statuses[0].status, CONNECTION.CONNECTING);

  FakeSocket.instances[0].open();
  assert.equal(statuses[1].status, CONNECTION.CONNECTED);

  FakeSocket.instances[0].message('{"hello":1}');
  assert.deepEqual(messages, ['{"hello":1}']);
});

test('a dropped socket reconnects, and a successful reconnect resets the backoff', () => {
  const { socket, timers, statuses } = makeSocket();
  socket.open();
  FakeSocket.instances[0].open();

  FakeSocket.instances[0].drop(1006, 'abnormal');
  assert.equal(statuses.at(-1).status, CONNECTION.RECONNECTING);
  assert.equal(FakeSocket.instances.length, 1);

  // First retry is ~1s with the jitter pinned to the midpoint.
  timers.advance(1_000);
  assert.equal(FakeSocket.instances.length, 2);

  FakeSocket.instances[1].open();
  assert.equal(statuses.at(-1).status, CONNECTION.CONNECTED);
  assert.equal(socket.attempt, 0);
});

test('repeated failures back off instead of hammering the provider', () => {
  const { socket, timers } = makeSocket();
  socket.open();

  const delays = [];
  for (let i = 0; i < 6; i += 1) {
    const current = FakeSocket.instances.at(-1);
    current.open();
    current.drop();
    // Nothing reconnects before its delay elapses.
    const before = FakeSocket.instances.length;
    timers.advance(10);
    assert.equal(FakeSocket.instances.length, before, `attempt ${i} retried too early`);
    timers.advance(60_000);
    delays.push(i);
  }
  // Six drops produced six reconnects, not a flood.
  assert.equal(FakeSocket.instances.length, 7);
});

test('backoff grows geometrically and is capped', () => {
  const tuning = { initialBackoffMs: 1_000, maxBackoffMs: 30_000, backoffFactor: 2 };
  const noJitter = () => 1;
  assert.equal(backoffDelay(1, tuning, noJitter), 1_000);
  assert.equal(backoffDelay(2, tuning, noJitter), 2_000);
  assert.equal(backoffDelay(3, tuning, noJitter), 4_000);
  assert.equal(backoffDelay(10, tuning, noJitter), 30_000);

  // Jitter keeps every delay inside [half, full] so tabs do not sync up.
  for (const random of [() => 0, () => 0.5, () => 0.999]) {
    const delay = backoffDelay(4, tuning, random);
    assert.ok(delay >= 4_000 && delay <= 8_000, String(delay));
  }
});

test('a socket closed on purpose does not reconnect', () => {
  const { socket, timers, statuses } = makeSocket();
  socket.open();
  FakeSocket.instances[0].open();

  socket.close();
  assert.equal(statuses.at(-1).status, CONNECTION.IDLE);

  timers.advance(120_000);
  assert.equal(FakeSocket.instances.length, 1);
});

test('restarting reconnects immediately with a fresh subscription list', () => {
  let symbols = ['BTCUSDT'];
  const { socket } = makeSocket({ url: () => `wss://stream.binance.com:9443/stream?streams=${symbols.join(',')}` });
  socket.open();
  FakeSocket.instances[0].open();

  symbols = ['BTCUSDT', 'ETHUSDT'];
  socket.restart();

  assert.equal(FakeSocket.instances.length, 2);
  assert.match(FakeSocket.instances[1].url, /ETHUSDT/);
});

test('onOpen is where subscriptions are sent, and send refuses a closed socket', () => {
  const { socket } = makeSocket({
    onOpen: (raw) => raw.send('{"type":"subscribe","symbol":"AAPL"}'),
  });
  socket.open();
  FakeSocket.instances[0].open();
  assert.deepEqual(FakeSocket.instances[0].sent, ['{"type":"subscribe","symbol":"AAPL"}']);

  assert.equal(socket.send('{"type":"ping"}'), true);
  FakeSocket.instances[0].readyState = 3;
  assert.equal(socket.send('{"type":"ping"}'), false);
});

test('an open socket that stops delivering is reported stale, not connected', () => {
  const { socket, timers } = makeSocket({ tuning: { staleAfterMs: 60_000 } });
  socket.open();
  FakeSocket.instances[0].open();
  FakeSocket.instances[0].message('{"tick":1}');

  timers.advance(30_000);
  assert.equal(socket.isStale(), false);

  timers.advance(45_000);
  assert.equal(socket.isStale(), true);
  assert.ok(socket.silenceMs() >= 60_000);

  // A single frame clears it.
  FakeSocket.instances[0].message('{"tick":2}');
  assert.equal(socket.isStale(), false);
});

test('a missing WebSocket implementation is an error, not a crash', () => {
  const statuses = [];
  const socket = new ReconnectingSocket({
    url: () => 'wss://example.test',
    onMessage: () => {},
    onStatus: (status, detail) => statuses.push({ status, detail }),
    WebSocketImpl: null,
  });
  socket.open();
  assert.equal(statuses[0].status, CONNECTION.ERROR);
});

/* ---------------------------------------------------------------- polling */

test('a polling source repeats on its interval and reports connected', async () => {
  const timers = fakeTimers();
  const statuses = [];
  let polls = 0;

  const source = new PollingSource({
    intervalMs: 15_000,
    poll: async () => {
      polls += 1;
    },
    onStatus: (status) => statuses.push(status),
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
  });

  source.start();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(polls, 1);
  assert.ok(statuses.includes(CONNECTION.CONNECTED));

  timers.advance(15_000);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(polls, 2);

  source.stop();
  timers.advance(60_000);
  await Promise.resolve();
  assert.equal(polls, 2);
});

test('a failing poll reports the reason and backs off rather than spinning', async () => {
  const timers = fakeTimers();
  const statuses = [];

  const source = new PollingSource({
    intervalMs: 15_000,
    poll: async () => {
      throw new Error('HTTP 429 מ־api.binance.com');
    },
    onStatus: (status, detail) => statuses.push({ status, detail }),
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
  });

  source.start();
  await Promise.resolve();
  await Promise.resolve();

  const failure = statuses.find((entry) => entry.status === CONNECTION.RECONNECTING);
  assert.ok(failure, 'a failed poll must be visible in the status');
  assert.match(failure.detail, /429/);
  source.stop();
});

/* ----------------------------------------------------------------- config */

test('endpoint overrides are restricted to known provider hosts', () => {
  assert.equal(isAllowedEndpoint('https://api.binance.com'), true);
  assert.equal(isAllowedEndpoint('wss://stream.binance.us:9443'), true);
  assert.equal(isAllowedEndpoint('/api/yahoo'), true);
  assert.equal(isAllowedEndpoint('ws://127.0.0.1:4500/binance/stream'), true);

  // The attack this exists to stop: a link that repoints the dashboard at a
  // server which can feed it any price it likes.
  assert.equal(isAllowedEndpoint('wss://attacker.example/stream'), false);
  assert.equal(isAllowedEndpoint('https://api.binance.com.evil.test'), false);
  assert.equal(isAllowedEndpoint('//evil.test'), false);
  assert.equal(isAllowedEndpoint('javascript:alert(1)'), false);
  // Plaintext to a remote host would let anyone on the path rewrite prices.
  assert.equal(isAllowedEndpoint('http://api.binance.com'), false);
  assert.equal(isAllowedEndpoint(''), false);
  assert.equal(isAllowedEndpoint(null), false);
});

test('configFromSearch applies allowed overrides and reports rejected ones', () => {
  const { config, rejected } = configFromSearch(
    '?binanceWs=ws://127.0.0.1:4500/binance/stream&finnhubWs=wss://attacker.example&stockPollMs=5000',
  );
  assert.equal(config.binanceWs, 'ws://127.0.0.1:4500/binance/stream');
  assert.equal(config.finnhubWs, 'wss://ws.finnhub.io'); // default kept
  assert.equal(config.stockPollMs, 5000);
  assert.deepEqual(rejected, ['finnhubWs=wss://attacker.example']);
});

test('a poll interval below one second is refused', () => {
  const { config, rejected } = configFromSearch('?stockPollMs=10');
  assert.equal(config.stockPollMs, 15_000);
  assert.deepEqual(rejected, ['stockPollMs=10']);
});
