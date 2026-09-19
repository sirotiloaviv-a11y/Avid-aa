/**
 * The alert engine.
 *
 * The engine is pure, so every case here is exact: a fixed clock, a fixed
 * series, and an assertion on precisely which rules fired. The cases that matter
 * most are the ones about *not* firing - a monitoring tool that alerts twenty
 * times for one event gets muted, and a muted alert is the same as no alert.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AlertHistory,
  DEFAULT_COOLDOWN_MS,
  RULE_TYPE,
  createRule,
  describeRule,
  evaluateRule,
  runAlertEngine,
  validateRule,
} from '../src/lib/alerts.js';
import { Series } from '../src/lib/series.js';

/**
 * Aligned to a whole minute. The series folds trades into fixed buckets, so a
 * fixture clock that sits mid-bucket shifts every synthetic candle by a fraction
 * of a bucket and quietly changes the arithmetic these tests assert on.
 */
const T0 = 1_699_999_980_000;

function makeContext({ price, open = null, candles = [], bucketMs = 60_000 }) {
  const series = new Series({ bucketMs, capacity: 500 });
  for (const candle of candles) series.applyCandle(candle);
  if (price !== undefined) series.lastPrice = price;
  return {
    asset: {
      key: 'binance:BTCUSDT',
      symbol: 'BTCUSDT',
      displaySymbol: 'BTC/USDT',
      name: 'Bitcoin',
      assetClass: 'crypto',
    },
    quote: price === undefined ? null : { key: 'binance:BTCUSDT', price, open, ts: T0 },
    series,
  };
}

function engine(rules, context, now = T0) {
  return runAlertEngine({ rules, contextFor: () => context, now });
}

/* ------------------------------------------------------------- price target */

test('a price rule fires when the target is crossed upward', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 70_000 });

  const below = engine([rule], makeContext({ price: 69_999 }));
  assert.equal(below.events.length, 0);

  const above = engine(below.rules, makeContext({ price: 70_001 }), T0 + 1000);
  assert.equal(above.events.length, 1);
  assert.equal(above.events[0].price, 70_001);
  assert.equal(above.rules[0].triggerCount, 1);
  assert.equal(above.rules[0].armed, false);
});

test('a price rule fires exactly at the target, not only past it', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 70_000 });
  assert.equal(engine([rule], makeContext({ price: 70_000 })).events.length, 1);
});

test('a downward price rule fires on the way down only', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'below', target: 60_000 });
  assert.equal(engine([rule], makeContext({ price: 60_001 })).events.length, 0);
  assert.equal(engine([rule], makeContext({ price: 59_999 })).events.length, 1);
});

test('a rule that stays met does not fire again on every tick', () => {
  let rules = [
    createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 70_000 }),
  ];
  let fired = 0;
  for (let i = 0; i < 25; i += 1) {
    const result = engine(rules, makeContext({ price: 70_500 + i }), T0 + i * 1000);
    rules = result.rules;
    fired += result.events.length;
  }
  assert.equal(fired, 1);
});

test('a rule re-arms when the condition lapses, and fires again after the cooldown', () => {
  let rules = [
    createRule({
      assetKey: 'binance:BTCUSDT',
      type: RULE_TYPE.PRICE,
      direction: 'above',
      target: 70_000,
      cooldownMs: 60_000,
    }),
  ];

  const first = engine(rules, makeContext({ price: 70_100 }), T0);
  assert.equal(first.events.length, 1);
  rules = first.rules;

  // Falls back below: the rule re-arms but must not fire on the way down.
  const lapse = engine(rules, makeContext({ price: 69_000 }), T0 + 10_000);
  assert.equal(lapse.events.length, 0);
  assert.equal(lapse.rules[0].armed, true);
  rules = lapse.rules;

  // Crosses again inside the cooldown: still silent.
  const tooSoon = engine(rules, makeContext({ price: 70_200 }), T0 + 20_000);
  assert.equal(tooSoon.events.length, 0);
  rules = tooSoon.rules;

  // And once the cooldown has elapsed, it speaks again.
  const later = engine(rules, makeContext({ price: 70_300 }), T0 + 61_000);
  assert.equal(later.events.length, 1);
  assert.equal(later.rules[0].triggerCount, 2);
});

test('a price flapping across the threshold is rate limited by the cooldown', () => {
  let rules = [
    createRule({
      assetKey: 'binance:BTCUSDT',
      type: RULE_TYPE.PRICE,
      direction: 'above',
      target: 100,
      cooldownMs: DEFAULT_COOLDOWN_MS,
    }),
  ];
  let fired = 0;
  // Twenty crossings inside five minutes.
  for (let i = 0; i < 20; i += 1) {
    const price = i % 2 === 0 ? 101 : 99;
    const result = engine(rules, makeContext({ price }), T0 + i * 10_000);
    rules = result.rules;
    fired += result.events.length;
  }
  assert.equal(fired, 1);
});

test('a disabled rule never fires and is left untouched', () => {
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.PRICE,
    direction: 'above',
    target: 100,
    enabled: false,
  });
  const result = engine([rule], makeContext({ price: 500 }));
  assert.equal(result.events.length, 0);
  assert.deepEqual(result.rules[0], rule);
});

/* ------------------------------------------------------------- percent spike */

test('a percent rule measures against the price one window ago', () => {
  const candles = [
    { t: T0 - 300_000, open: 100, high: 100, low: 100, close: 100, volume: 10 },
    { t: T0 - 240_000, open: 100, high: 101, low: 100, close: 101, volume: 10 },
    { t: T0 - 60_000, open: 101, high: 106, low: 101, close: 106, volume: 10 },
  ];
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.PERCENT,
    thresholdPct: 5,
    move: 'up',
    basis: 'window',
    windowMs: 300_000,
  });

  const context = makeContext({ price: 106, candles });
  const outcome = evaluateRule(rule, context, T0);
  assert.equal(outcome.met, true);
  assert.ok(Math.abs(outcome.value - 6) < 1e-9);
});

test('a percent rule does not fire below its threshold', () => {
  const candles = [{ t: T0 - 300_000, open: 100, high: 100, low: 100, close: 100, volume: 1 }];
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.PERCENT,
    thresholdPct: 5,
    move: 'up',
    windowMs: 300_000,
  });
  assert.equal(evaluateRule(rule, makeContext({ price: 104, candles }), T0).met, false);
});

test('direction filters work: an "up" rule ignores a crash, and vice versa', () => {
  const candles = [{ t: T0 - 300_000, open: 100, high: 100, low: 100, close: 100, volume: 1 }];
  const up = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PERCENT, thresholdPct: 5, move: 'up', windowMs: 300_000 });
  const down = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PERCENT, thresholdPct: 5, move: 'down', windowMs: 300_000 });
  const both = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PERCENT, thresholdPct: 5, move: 'both', windowMs: 300_000 });

  const crash = makeContext({ price: 90, candles });
  assert.equal(evaluateRule(up, crash, T0).met, false);
  assert.equal(evaluateRule(down, crash, T0).met, true);
  assert.equal(evaluateRule(both, crash, T0).met, true);

  const rally = makeContext({ price: 110, candles });
  assert.equal(evaluateRule(up, rally, T0).met, true);
  assert.equal(evaluateRule(down, rally, T0).met, false);
  assert.equal(evaluateRule(both, rally, T0).met, true);
});

test('a percent rule against the day open uses the quote, not the series', () => {
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.PERCENT,
    thresholdPct: 3,
    move: 'both',
    basis: 'dayOpen',
  });
  const context = makeContext({ price: 104, open: 100 });
  const outcome = evaluateRule(rule, context, T0);
  assert.equal(outcome.met, true);
  assert.ok(Math.abs(outcome.value - 4) < 1e-9);
});

test('a percent rule with no history reports why instead of silently passing', () => {
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.PERCENT,
    thresholdPct: 5,
    windowMs: 3_600_000,
  });
  const outcome = evaluateRule(rule, makeContext({ price: 100 }), T0);
  assert.equal(outcome.met, false);
  assert.match(outcome.reason, /היסטוריה/);

  // And the diagnostic reaches the engine's caller, so the UI can show it.
  const result = engine([rule], makeContext({ price: 100 }));
  assert.match(result.diagnostics[rule.id], /היסטוריה/);
});

test('a day-open percent rule with no open price says so', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PERCENT, thresholdPct: 3, basis: 'dayOpen' });
  const outcome = evaluateRule(rule, makeContext({ price: 100, open: null }), T0);
  assert.equal(outcome.met, false);
  assert.match(outcome.reason, /פתיחה/);
});

/* -------------------------------------------------------------- volume surge */

function volumeCandles(perBucket, buckets, startOffsetMs) {
  const candles = [];
  for (let i = 0; i < buckets; i += 1) {
    const t = T0 - startOffsetMs + i * 60_000;
    candles.push({ t, open: 100, high: 100, low: 100, close: 100, volume: perBucket });
  }
  return candles;
}

test('a volume rule fires when the window beats the baseline by the multiple', () => {
  // 60 baseline minutes at 10 per minute, then 5 minutes at 40 per minute.
  const baseline = volumeCandles(10, 60, 65 * 60_000);
  const surge = volumeCandles(40, 5, 5 * 60_000);
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.VOLUME,
    multiple: 3,
    windowMs: 300_000,
    baselineWindows: 12,
  });

  const context = makeContext({ price: 100, candles: [...baseline, ...surge] });
  const outcome = evaluateRule(rule, context, T0);
  assert.equal(outcome.met, true);
  assert.ok(Math.abs(outcome.value - 4) < 1e-9, `ratio was ${outcome.value}`);
});

test('ordinary volume does not trip a volume rule', () => {
  const candles = volumeCandles(10, 65, 65 * 60_000);
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.VOLUME,
    multiple: 3,
    windowMs: 300_000,
    baselineWindows: 12,
  });
  const outcome = evaluateRule(rule, makeContext({ price: 100, candles }), T0);
  assert.equal(outcome.met, false);
  assert.ok(Math.abs(outcome.value - 1) < 1e-9);
});

test('a volume rule refuses to fire before it has a baseline to compare against', () => {
  // Three minutes of history against a rule that wants an hour of baseline: a
  // naive implementation would divide by a tiny average and fire immediately.
  const candles = volumeCandles(1000, 3, 3 * 60_000);
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.VOLUME,
    multiple: 3,
    windowMs: 300_000,
    baselineWindows: 12,
  });
  const outcome = evaluateRule(rule, makeContext({ price: 100, candles }), T0);
  assert.equal(outcome.met, false);
  assert.match(outcome.reason, /מחזור/);
});

test('a zero-volume baseline cannot produce a division by zero', () => {
  const baseline = volumeCandles(0, 60, 65 * 60_000);
  const surge = volumeCandles(50, 5, 5 * 60_000);
  const rule = createRule({
    assetKey: 'binance:BTCUSDT',
    type: RULE_TYPE.VOLUME,
    multiple: 3,
    windowMs: 300_000,
    baselineWindows: 12,
  });
  const outcome = evaluateRule(rule, makeContext({ price: 100, candles: [...baseline, ...surge] }), T0);
  assert.equal(outcome.met, false);
  assert.equal(outcome.value, null);
  assert.match(outcome.reason, /אפס/);
});

/* ----------------------------------------------------------------- the event */

test('an event carries the full name and the symbol together', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 100 });
  const [event] = engine([rule], makeContext({ price: 150 })).events;
  // This is the requirement the notification title depends on.
  assert.equal(event.title, 'Bitcoin / BTC/USDT');
  assert.equal(event.name, 'Bitcoin');
  assert.equal(event.displaySymbol, 'BTC/USDT');
  assert.equal(event.symbol, 'BTCUSDT');
  assert.equal(event.type, 'price');
  assert.equal(event.ts, T0);
  assert.match(event.body, /150/);
  assert.match(event.ruleLabel, /100/);
});

test('an asset with no resolved name falls back to the symbol, never a guess', () => {
  const context = makeContext({ price: 150 });
  context.asset = { key: 'binance:NEWCOIN', symbol: 'NEWCOIN', displaySymbol: 'NEW/USDT', name: null };
  const rule = createRule({ assetKey: 'binance:NEWCOIN', type: RULE_TYPE.PRICE, direction: 'above', target: 100 });
  const [event] = engine([rule], context).events;
  assert.equal(event.title, 'NEW/USDT');
  assert.equal(event.name, null);
});

test('a rule whose asset is gone reports it instead of throwing', () => {
  const rule = createRule({ assetKey: 'binance:GONE', type: RULE_TYPE.PRICE, direction: 'above', target: 1 });
  const result = runAlertEngine({ rules: [rule], contextFor: () => null, now: T0 });
  assert.equal(result.events.length, 0);
  assert.match(result.diagnostics[rule.id], /רשימת המעקב/);
});

test('a rule on an asset with no price yet waits quietly', () => {
  const rule = createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'below', target: 100 });
  const context = makeContext({ price: undefined });
  context.series.lastPrice = null;
  const result = engine([rule], context);
  assert.equal(result.events.length, 0);
  assert.match(result.diagnostics[rule.id], /מחיר/);
});

test('several rules on several assets each fire independently', () => {
  const btc = makeContext({ price: 70_500 });
  const ethContext = makeContext({ price: 3_000 });
  ethContext.asset = { key: 'binance:ETHUSDT', symbol: 'ETHUSDT', displaySymbol: 'ETH/USDT', name: 'Ethereum' };

  const rules = [
    createRule({ assetKey: 'binance:BTCUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 70_000 }),
    createRule({ assetKey: 'binance:ETHUSDT', type: RULE_TYPE.PRICE, direction: 'above', target: 4_000 }),
    createRule({ assetKey: 'binance:ETHUSDT', type: RULE_TYPE.PRICE, direction: 'below', target: 3_500 }),
  ];

  const result = runAlertEngine({
    rules,
    contextFor: (key) => (key === 'binance:BTCUSDT' ? btc : ethContext),
    now: T0,
  });
  assert.equal(result.events.length, 2);
  assert.deepEqual(result.events.map((event) => event.title).sort(), [
    'Bitcoin / BTC/USDT',
    'Ethereum / ETH/USDT',
  ]);
});

/* ------------------------------------------------------------- form handling */

test('validateRule catches the mistakes a form can produce', () => {
  assert.deepEqual(validateRule({ assetKey: 'k', type: RULE_TYPE.PRICE, target: 100 }), {});

  assert.ok(validateRule({ assetKey: '', type: RULE_TYPE.PRICE, target: 100 }).assetKey);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PRICE, target: 0 }).target);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PRICE, target: -5 }).target);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PRICE, target: Number.NaN }).target);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: 0, windowMs: 300_000 }).thresholdPct);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: 150, windowMs: 300_000 }).thresholdPct);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: 5, windowMs: 1000 }).windowMs);
  assert.ok(validateRule({ assetKey: 'k', type: RULE_TYPE.VOLUME, multiple: 1, windowMs: 300_000 }).multiple);
  assert.ok(validateRule({ assetKey: 'k', type: 'nonsense' }).type);

  // A day-open percent rule needs no window, so none is demanded.
  assert.deepEqual(
    validateRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: 3, basis: 'dayOpen' }),
    {},
  );
});

test('createRule fills defaults and normalises stray input', () => {
  const rule = createRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: -8, move: 'sideways' });
  assert.equal(rule.thresholdPct, 8); // magnitude
  assert.equal(rule.move, 'both'); // unknown value falls back
  assert.equal(rule.enabled, true);
  assert.equal(rule.armed, true);
  assert.equal(rule.triggerCount, 0);
  assert.equal(rule.cooldownMs, DEFAULT_COOLDOWN_MS);
  assert.throws(() => createRule({ assetKey: 'k', type: 'bogus' }), /Unknown rule type/);
});

test('describeRule states what each rule watches, in Hebrew', () => {
  assert.match(
    describeRule(createRule({ assetKey: 'k', type: RULE_TYPE.PRICE, direction: 'above', target: 70_000 })),
    /מעל/,
  );
  assert.match(
    describeRule(createRule({ assetKey: 'k', type: RULE_TYPE.PERCENT, thresholdPct: 5, windowMs: 300_000 })),
    /5%/,
  );
  assert.match(
    describeRule(createRule({ assetKey: 'k', type: RULE_TYPE.VOLUME, multiple: 3, windowMs: 300_000 })),
    /פי 3/,
  );
});

/* ---------------------------------------------------------------- the history */

test('the history keeps newest first and stays bounded', () => {
  const history = new AlertHistory(5);
  for (let i = 0; i < 8; i += 1) {
    history.add([{ id: `e${i}`, ts: T0 + i, title: `event ${i}` }]);
  }
  assert.equal(history.length, 5);
  assert.equal(history.entries[0].id, 'e7');
  assert.equal(history.entries[4].id, 'e3');
});

test('a batch of events is logged newest first within the batch', () => {
  const history = new AlertHistory(10);
  history.add([
    { id: 'first', ts: T0 },
    { id: 'second', ts: T0 + 1 },
  ]);
  assert.deepEqual(history.entries.map((entry) => entry.id), ['second', 'first']);
});
