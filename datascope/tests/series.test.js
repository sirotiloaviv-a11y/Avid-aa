/**
 * The rolling series and the market store.
 *
 * The invariant worth defending here is boundedness. This runs for hours against
 * feeds that send several messages a second; if the series grew with uptime the
 * tab would eventually die, and it would die overnight, unattended, which is
 * exactly when a monitoring dashboard is supposed to be working.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { Series, SeriesStore } from '../src/lib/series.js';
import { MarketStore, intradayStats, topMovers } from '../src/lib/market.js';
import { buildAsset } from '../src/lib/assets.js';

const T0 = 1_699_999_980_000; // whole minute

test('trades fold into one candle per bucket', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.addTrade(100, 1, T0 + 1_000);
  series.addTrade(105, 2, T0 + 20_000);
  series.addTrade(95, 3, T0 + 40_000);
  series.addTrade(102, 4, T0 + 61_000); // next bucket

  assert.equal(series.length, 2);
  assert.deepEqual(series.candles[0], {
    t: T0,
    open: 100,
    high: 105,
    low: 95,
    close: 95,
    volume: 6,
  });
  assert.equal(series.candles[1].t, T0 + 60_000);
  assert.equal(series.candles[1].open, 102);
  assert.equal(series.lastPrice, 102);
});

test('the series never grows past its capacity', () => {
  const series = new Series({ bucketMs: 60_000, capacity: 10 });
  for (let i = 0; i < 500; i += 1) series.addTrade(100 + i, 1, T0 + i * 60_000);
  assert.equal(series.length, 10);
  // The window that survives is the most recent one.
  assert.equal(series.candles[9].close, 599);
  assert.equal(series.candles[0].t, T0 + 490 * 60_000);
});

test('thousands of trades in one bucket cost one candle', () => {
  const series = new Series({ bucketMs: 60_000, capacity: 240 });
  for (let i = 0; i < 20_000; i += 1) series.addTrade(100 + (i % 7), 0.5, T0 + (i % 60) * 1000);
  assert.equal(series.length, 1);
  assert.equal(series.candles[0].volume, 10_000);
});

test('an open candle is revised in place, not appended twice', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.applyCandle({ t: T0, open: 100, high: 101, low: 99, close: 100, volume: 5 });
  series.applyCandle({ t: T0, open: 100, high: 103, low: 99, close: 103, volume: 9 });
  assert.equal(series.length, 1);
  assert.equal(series.candles[0].close, 103);
  assert.equal(series.candles[0].volume, 9);
  assert.equal(series.lastPrice, 103);
});

test('a late candle is inserted in time order, never appended out of order', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.applyCandle({ t: T0 + 120_000, open: 3, high: 3, low: 3, close: 3, volume: 1 });
  series.applyCandle({ t: T0, open: 1, high: 1, low: 1, close: 1, volume: 1 });
  series.applyCandle({ t: T0 + 60_000, open: 2, high: 2, low: 2, close: 2, volume: 1 });

  assert.deepEqual(series.candles.map((candle) => candle.close), [1, 2, 3]);
  // A late arrival must not rewrite the live price backwards.
  assert.equal(series.lastPrice, 3);
});

test('an out-of-order trade folds into its own bucket without reordering', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.addTrade(100, 1, T0);
  series.addTrade(110, 1, T0 + 60_000);
  series.addTrade(90, 5, T0 + 30_000); // belongs to the first bucket

  assert.deepEqual(series.candles.map((candle) => candle.t), [T0, T0 + 60_000]);
  assert.equal(series.candles[0].low, 90);
  assert.equal(series.candles[0].volume, 6);
  assert.equal(series.lastPrice, 110);
});

test('priceAt returns the close at or before a time, or null before any history', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.applyCandle({ t: T0, open: 1, high: 1, low: 1, close: 100, volume: 1 });
  series.applyCandle({ t: T0 + 60_000, open: 1, high: 1, low: 1, close: 110, volume: 1 });

  assert.equal(series.priceAt(T0 - 1), null);
  assert.equal(series.priceAt(T0), 100);
  assert.equal(series.priceAt(T0 + 30_000), 100);
  assert.equal(series.priceAt(T0 + 120_000), 110);
});

test('volumeSince and averageVolume cover the ranges the alert engine asks for', () => {
  const series = new Series({ bucketMs: 60_000 });
  for (let i = 0; i < 10; i += 1) {
    series.applyCandle({ t: T0 + i * 60_000, open: 1, high: 1, low: 1, close: 1, volume: 10 });
  }
  assert.equal(series.volumeSince(T0 + 5 * 60_000), 50);
  assert.equal(series.averageVolume(T0, T0 + 5 * 60_000), 10);
  // An empty range gives null rather than zero, so a rule cannot divide by it.
  assert.equal(series.averageVolume(T0 - 10 * 60_000, T0 - 5 * 60_000), null);
});

test('seeding replaces history, sorts it, and respects capacity', () => {
  const series = new Series({ bucketMs: 60_000, capacity: 3 });
  series.seed([
    { t: T0 + 120_000, open: 3, high: 3, low: 3, close: 3, volume: 1 },
    { t: T0, open: 1, high: 1, low: 1, close: 1, volume: 1 },
    { t: T0 + 60_000, open: 2, high: 2, low: 2, close: 2, volume: 1 },
    { t: T0 + 180_000, open: 4, high: 4, low: 4, close: 4, volume: 1 },
  ]);
  assert.equal(series.length, 3);
  assert.deepEqual(series.candles.map((candle) => candle.close), [2, 3, 4]);
  assert.equal(series.lastPrice, 4);
});

test('a summary over an empty series is empty, not zero-priced', () => {
  const summary = new Series().summary();
  assert.equal(summary.open, null);
  assert.equal(summary.high, null);
  assert.equal(summary.count, 0);
});

test('SeriesStore hands out one series per key', () => {
  const store = new SeriesStore({ bucketMs: 60_000 });
  const a = store.get('binance:BTCUSDT');
  const b = store.get('binance:BTCUSDT');
  const c = store.get('binance:ETHUSDT');
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.equal(store.peek('nothing:HERE'), null);
});

/* ------------------------------------------------------------- market store */

function btc() {
  return buildAsset({ provider: 'binance', symbol: 'BTCUSDT', assetClass: 'crypto', base: 'BTC', currency: 'USDT' });
}

test('a quote older than the one held is ignored', () => {
  const market = new MarketStore();
  market.watch(btc());

  market.applyQuote({ key: 'binance:BTCUSDT', price: 100, ts: T0 + 1000, source: 'binance', delayed: false });
  const applied = market.applyQuote({
    key: 'binance:BTCUSDT',
    price: 50,
    ts: T0, // older
    source: 'binance',
    delayed: false,
  });

  assert.equal(applied, false);
  assert.equal(market.quote('binance:BTCUSDT').price, 100);
});

test('a later partial quote does not erase fields an earlier one supplied', () => {
  const market = new MarketStore();
  market.watch(btc());
  market.applyQuote({
    key: 'binance:BTCUSDT',
    price: 100,
    open: 90,
    prevClose: 88,
    dayHigh: 105,
    ts: T0,
    source: 'binance',
    delayed: false,
  });
  // A trade-stream style update carrying only a price.
  market.applyQuote({ key: 'binance:BTCUSDT', price: 101, ts: T0 + 1000, source: 'binance', delayed: false });

  const quote = market.quote('binance:BTCUSDT');
  assert.equal(quote.price, 101);
  assert.equal(quote.open, 90);
  assert.equal(quote.prevClose, 88);
  assert.equal(quote.dayHigh, 105);
  // Derived from the previous close, not the open.
  assert.ok(Math.abs(quote.changePct - ((101 - 88) / 88) * 100) < 1e-9);
});

test('trades build the series and keep the quote current', () => {
  const market = new MarketStore();
  market.watch(buildAsset({ provider: 'finnhub', symbol: 'AAPL', assetClass: 'stock', currency: 'USD' }));
  market.applyQuote({
    key: 'finnhub:AAPL',
    price: 100,
    prevClose: 100,
    ts: T0,
    source: 'finnhub',
    delayed: false,
  });

  market.applyTrade({ key: 'finnhub:AAPL', price: 104, size: 10, ts: T0 + 1_000 });
  market.applyTrade({ key: 'finnhub:AAPL', price: 108, size: 5, ts: T0 + 2_000 });

  const quote = market.quote('finnhub:AAPL');
  assert.equal(quote.price, 108);
  // The day's open survived the trade updates, so the change stays meaningful.
  assert.equal(quote.prevClose, 100);
  assert.ok(Math.abs(quote.changePct - 8) < 1e-9);

  const series = market.series.peek('finnhub:AAPL');
  assert.equal(series.length, 1);
  assert.equal(series.candles[0].volume, 15);
});

test('contextFor gives the alert engine everything it needs, or null', () => {
  const market = new MarketStore();
  market.watch(btc());
  market.applyQuote({ key: 'binance:BTCUSDT', price: 100, ts: T0, source: 'binance', delayed: false });

  const context = market.contextFor('binance:BTCUSDT');
  assert.equal(context.asset.displaySymbol, 'BTC/USDT');
  assert.equal(context.quote.price, 100);
  assert.ok(context.series);
  assert.equal(market.contextFor('binance:NOTHING'), null);
});

test('unwatching removes the asset, its quote and its series', () => {
  const market = new MarketStore();
  market.watch(btc());
  market.applyQuote({ key: 'binance:BTCUSDT', price: 100, ts: T0, source: 'binance', delayed: false });
  market.unwatch('binance:BTCUSDT');

  assert.equal(market.watchlist().length, 0);
  assert.equal(market.quote('binance:BTCUSDT'), null);
  assert.equal(market.series.peek('binance:BTCUSDT'), null);
  assert.equal(market.contextFor('binance:BTCUSDT'), null);
});

test('watching the same asset twice does not duplicate it', () => {
  const market = new MarketStore();
  market.watch(btc());
  market.watch(btc());
  assert.equal(market.watchlist().length, 1);
});

test('topMovers ranks by the size of the move, in either direction', () => {
  const rows = [
    { asset: { key: 'a' }, quote: { changePct: 2 } },
    { asset: { key: 'b' }, quote: { changePct: -9 } },
    { asset: { key: 'c' }, quote: { changePct: 5 } },
    { asset: { key: 'd' }, quote: { changePct: null } },
    { asset: { key: 'e' }, quote: null },
  ];
  const movers = topMovers(rows, { limit: 3 });
  assert.deepEqual(movers.map((row) => row.asset.key), ['b', 'c', 'a']);
});

test('intradayStats prefers provider figures and falls back to what was observed', () => {
  const series = new Series({ bucketMs: 60_000 });
  series.applyCandle({ t: T0, open: 10, high: 12, low: 9, close: 11, volume: 100 });

  const withProvider = intradayStats(
    { price: 11, open: 10, prevClose: 9.5, dayHigh: 20, dayLow: 5, volume: 999, changePct: 1, ts: T0, delayed: false, source: 'binance' },
    series,
  );
  assert.equal(withProvider.high, 20); // the exchange's figure wins
  assert.equal(withProvider.volume, 999);

  const withoutProvider = intradayStats(null, series);
  assert.equal(withoutProvider.high, 12); // observed locally
  assert.equal(withoutProvider.observedVolume, 100);
  // With no quote at all the last traded price still comes from the series, but
  // nothing is claimed about its provenance or its freshness.
  assert.equal(withoutProvider.price, 11);
  assert.equal(withoutProvider.source, null);
  assert.equal(withoutProvider.changePct, null);
  assert.equal(withoutProvider.delayed, false);
});
