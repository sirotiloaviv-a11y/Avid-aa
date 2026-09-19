/**
 * Provider parsing, against payloads shaped exactly like the real ones.
 *
 * The fixtures below are the documented wire formats of each provider: Binance's
 * string-valued numeric fields, Finnhub's second-resolution timestamps and
 * batched trade frames, Yahoo's null-padded candle arrays. Getting any of those
 * details wrong produces a plausible-looking price that is silently wrong, which
 * is why each one has a test that would catch it.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import * as binance from '../src/providers/binance.js';
import * as finnhub from '../src/providers/finnhub.js';
import * as yahoo from '../src/providers/yahoo.js';
import * as coingecko from '../src/providers/coingecko.js';
import { toNumber } from '../src/lib/model.js';

/* ------------------------------------------------------------------ binance */

const BINANCE_TICKER = {
  e: '24hrTicker',
  E: 1_700_000_000_000,
  s: 'BTCUSDT',
  p: '-1250.00000000',
  P: '-1.923',
  w: '64500.00000000',
  x: '65000.00000000',
  c: '63750.50000000',
  Q: '0.01000000',
  b: '63750.00000000',
  B: '1.00000000',
  a: '63751.00000000',
  A: '1.00000000',
  o: '65000.50000000',
  h: '65500.00000000',
  l: '63500.00000000',
  v: '12345.67800000',
  q: '789012345.00000000',
  O: 1_699_913_600_000,
  C: 1_700_000_000_000,
  F: 1,
  L: 2,
  n: 2,
};

test('binance: a 24h ticker becomes a quote with every numeric field parsed', () => {
  const quote = binance.parseTickerEvent(BINANCE_TICKER);
  assert.equal(quote.key, 'binance:BTCUSDT');
  assert.equal(quote.price, 63750.5);
  assert.equal(quote.open, 65000.5);
  assert.equal(quote.prevClose, 65000);
  assert.equal(quote.dayHigh, 65500);
  assert.equal(quote.dayLow, 63500);
  assert.equal(quote.changeAbs, -1250);
  assert.equal(quote.changePct, -1.923);
  assert.equal(quote.volume, 12345.678);
  assert.equal(quote.quoteVolume, 789012345);
  assert.equal(quote.ts, 1_700_000_000_000);
  assert.equal(quote.source, 'binance');
  assert.equal(quote.delayed, false);
  // Strings on the wire must not survive as strings.
  for (const field of ['price', 'open', 'dayHigh', 'volume']) {
    assert.equal(typeof quote[field], 'number', field);
  }
});

test('binance: a non-ticker payload is rejected rather than half-parsed', () => {
  assert.equal(binance.parseTickerEvent({ e: 'aggTrade', s: 'BTCUSDT', p: '1' }), null);
  assert.equal(binance.parseTickerEvent(null), null);
  assert.equal(binance.parseTickerEvent({}), null);
});

test('binance: a kline event carries the candle and whether it closed', () => {
  const frame = {
    e: 'kline',
    E: 1_700_000_000_000,
    s: 'ETHUSDT',
    k: {
      t: 1_699_999_980_000,
      T: 1_700_000_039_999,
      s: 'ETHUSDT',
      i: '1m',
      o: '3200.10000000',
      c: '3205.40000000',
      h: '3206.00000000',
      l: '3199.00000000',
      v: '150.50000000',
      x: false,
      q: '482000.00000000',
    },
  };
  const parsed = binance.parseKlineEvent(frame);
  assert.equal(parsed.key, 'binance:ETHUSDT');
  assert.equal(parsed.closed, false);
  assert.deepEqual(parsed.candle, {
    t: 1_699_999_980_000,
    open: 3200.1,
    high: 3206,
    low: 3199,
    close: 3205.4,
    volume: 150.5,
  });

  frame.k.x = true;
  assert.equal(binance.parseKlineEvent(frame).closed, true);
});

test('binance: combined-stream frames are unwrapped, raw frames pass through', () => {
  const combined = JSON.stringify({ stream: 'btcusdt@ticker', data: BINANCE_TICKER });
  const fromCombined = binance.parseSocketMessage(combined);
  assert.equal(fromCombined.kind, 'quote');
  assert.equal(fromCombined.quote.price, 63750.5);

  const direct = binance.parseSocketMessage(JSON.stringify(BINANCE_TICKER));
  assert.equal(direct.kind, 'quote');
  assert.equal(direct.quote.price, 63750.5);
});

test('binance: malformed socket text is ignored, not thrown', () => {
  assert.equal(binance.parseSocketMessage('not json'), null);
  assert.equal(binance.parseSocketMessage('{"result":null,"id":1}'), null);
  assert.equal(binance.parseSocketMessage('[]'), null);
});

test('binance: REST tickers parse, and rows without a price are dropped', () => {
  const quotes = binance.parseRestTickers([
    {
      symbol: 'BTCUSDT',
      priceChange: '100.00',
      priceChangePercent: '0.15',
      lastPrice: '64100.00',
      openPrice: '64000.00',
      prevClosePrice: '64000.00',
      highPrice: '64500.00',
      lowPrice: '63900.00',
      volume: '1000.00',
      quoteVolume: '64000000.00',
      closeTime: 1_700_000_000_000,
    },
    { symbol: 'BROKEN', lastPrice: 'n/a' },
  ]);
  assert.equal(quotes.length, 1);
  assert.equal(quotes[0].price, 64100);
  assert.equal(quotes[0].changePct, 0.15);
});

test('binance: klines arrive as positional arrays', () => {
  const candles = binance.parseRestKlines([
    [1_700_000_000_000, '100.0', '105.0', '99.0', '104.0', '12.5', 1_700_000_059_999, '1300', 42, '0', '0', '0'],
    ['bad row'],
  ]);
  assert.equal(candles.length, 1);
  assert.deepEqual(candles[0], {
    t: 1_700_000_000_000,
    open: 100,
    high: 105,
    low: 99,
    close: 104,
    volume: 12.5,
  });
});

test('binance: exchangeInfo keeps only tradable pairs and the requested quotes', () => {
  const assets = binance.parseExchangeInfo(
    {
      symbols: [
        { symbol: 'BTCUSDT', status: 'TRADING', baseAsset: 'BTC', quoteAsset: 'USDT' },
        { symbol: 'OLDCOIN', status: 'BREAK', baseAsset: 'OLD', quoteAsset: 'USDT' },
        { symbol: 'ETHBTC', status: 'TRADING', baseAsset: 'ETH', quoteAsset: 'BTC' },
      ],
    },
    { quoteAssets: ['USDT'] },
  );
  assert.equal(assets.length, 1);
  assert.equal(assets[0].symbol, 'BTCUSDT');
  assert.equal(assets[0].displaySymbol, 'BTC/USDT');
  assert.equal(assets[0].assetClass, 'crypto');
  // exchangeInfo has no names, and none is invented.
  assert.equal(assets[0].name, null);
});

test('binance: the stream URL lists one stream per symbol and channel', () => {
  const url = binance.streamUrl(['BTCUSDT', 'ETHUSDT'], { ws: 'wss://example.test' });
  assert.equal(
    url,
    'wss://example.test/stream?streams=btcusdt@ticker/btcusdt@kline_1m/ethusdt@ticker/ethusdt@kline_1m',
  );
});

/* ------------------------------------------------------------------ finnhub */

test('finnhub: a trade frame yields one trade per entry, in milliseconds', () => {
  const parsed = finnhub.parseSocketMessage(
    JSON.stringify({
      type: 'trade',
      data: [
        { s: 'AAPL', p: 185.24, t: 1_700_000_000_000, v: 100 },
        { s: 'MSFT', p: 415.1, t: 1_700_000_000_500, v: 50 },
      ],
    }),
  );
  assert.equal(parsed.kind, 'trades');
  assert.equal(parsed.trades.length, 2);
  assert.deepEqual(parsed.trades[0], {
    key: 'finnhub:AAPL',
    price: 185.24,
    size: 100,
    ts: 1_700_000_000_000,
  });
});

test('finnhub: ping and error frames are recognised, junk is not', () => {
  assert.deepEqual(finnhub.parseSocketMessage('{"type":"ping"}'), { kind: 'ping' });
  assert.deepEqual(finnhub.parseSocketMessage('{"type":"error","msg":"Invalid token"}'), {
    kind: 'error',
    message: 'Invalid token',
  });
  assert.equal(finnhub.parseSocketMessage('{"type":"trade","data":[]}'), null);
  assert.equal(finnhub.parseSocketMessage('nonsense'), null);
});

test('finnhub: /quote seconds become milliseconds', () => {
  const quote = finnhub.parseQuote('AAPL', {
    c: 261.74,
    d: 2.63,
    dp: 1.0154,
    h: 263.31,
    l: 260.68,
    o: 261.07,
    pc: 259.11,
    t: 1_582_641_000,
  });
  assert.equal(quote.key, 'finnhub:AAPL');
  assert.equal(quote.price, 261.74);
  assert.equal(quote.prevClose, 259.11);
  assert.equal(quote.ts, 1_582_641_000_000);
  assert.equal(quote.volume, null);
});

test('finnhub: the all-zero quote of an unknown symbol is rejected', () => {
  assert.equal(finnhub.parseQuote('NOPE', { c: 0, d: null, dp: null, h: 0, l: 0, o: 0, pc: 0, t: 0 }), null);
});

test('finnhub: search drops cross-listings and tidies shouting names', () => {
  const assets = finnhub.parseSearch({
    count: 3,
    result: [
      { description: 'APPLE INC', displaySymbol: 'AAPL', symbol: 'AAPL', type: 'Common Stock' },
      { description: 'APPLE INC', displaySymbol: 'APC.DE', symbol: 'APC.DE', type: 'Common Stock' },
      { description: 'SOME FUND', displaySymbol: 'XYZ', symbol: 'XYZ', type: 'ETP' },
    ],
  });
  assert.equal(assets.length, 1);
  assert.equal(assets[0].symbol, 'AAPL');
  assert.equal(assets[0].name, 'Apple Inc');
  assert.equal(assets[0].assetClass, 'stock');
});

/* -------------------------------------------------------------------- yahoo */

const YAHOO_CHART = {
  chart: {
    result: [
      {
        meta: {
          currency: 'USD',
          symbol: 'AAPL',
          exchangeName: 'NMS',
          longName: 'Apple Inc.',
          regularMarketPrice: 228.52,
          chartPreviousClose: 226.8,
          regularMarketDayHigh: 229.1,
          regularMarketDayLow: 226.5,
          regularMarketTime: 1_700_000_100,
        },
        timestamp: [1_700_000_000, 1_700_000_060, 1_700_000_120],
        indicators: {
          quote: [
            {
              open: [227.0, 227.8, null],
              high: [227.9, 228.6, null],
              low: [226.9, 227.5, null],
              close: [227.8, 228.52, null],
              volume: [12000, 15000, null],
            },
          ],
        },
      },
    ],
    error: null,
  },
};

test('yahoo: the chart response yields a delayed quote', () => {
  const quote = yahoo.parseChartQuote(YAHOO_CHART);
  assert.equal(quote.key, 'yahoo:AAPL');
  assert.equal(quote.price, 228.52);
  assert.equal(quote.prevClose, 226.8);
  assert.equal(quote.ts, 1_700_000_100_000);
  // Yahoo promises no real time, and the UI needs to be able to say so.
  assert.equal(quote.delayed, true);
  // changePct is derived from the previous close when Yahoo omits it.
  assert.ok(Math.abs(quote.changePct - 0.7584) < 0.001);
});

test('yahoo: null-padded minutes are dropped, never carried forward', () => {
  const candles = yahoo.parseChartCandles(YAHOO_CHART);
  assert.equal(candles.length, 2);
  assert.equal(candles[0].t, 1_700_000_000_000);
  assert.equal(candles[1].close, 228.52);
  assert.equal(candles[1].volume, 15000);
});

test('yahoo: the asset name comes from meta', () => {
  assert.deepEqual(yahoo.parseChartAsset(YAHOO_CHART), {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    currency: 'USD',
  });
});

test('yahoo: an error inside a 200 response is surfaced', () => {
  const message = yahoo.parseChartError({
    chart: { result: null, error: { code: 'Not Found', description: 'No data found, symbol may be delisted' } },
  });
  assert.match(message, /Not Found/);
  assert.equal(yahoo.parseChartError(YAHOO_CHART), null);
  assert.equal(yahoo.parseChartQuote({ chart: { result: null, error: {} } }), null);
});

test('yahoo: search keeps US equities and drops the rest', () => {
  const assets = yahoo.parseSearch({
    quotes: [
      { symbol: 'AAPL', shortname: 'Apple Inc.', longname: 'Apple Inc.', quoteType: 'EQUITY' },
      { symbol: 'BTC-USD', shortname: 'Bitcoin USD', quoteType: 'CRYPTOCURRENCY' },
      { symbol: 'APC.DE', shortname: 'Apple', quoteType: 'EQUITY' },
      { symbol: 'SPY', shortname: 'SPDR S&P 500', quoteType: 'ETF' },
    ],
  });
  assert.deepEqual(assets.map((asset) => asset.symbol), ['AAPL', 'SPY']);
  assert.equal(assets[0].name, 'Apple Inc.');
});

/* ---------------------------------------------------------------- coingecko */

test('coingecko: the coin list maps ticker codes to names, first entry winning', () => {
  const names = coingecko.parseCoinList([
    { id: 'bitcoin', symbol: 'btc', name: 'Bitcoin' },
    { id: 'bitcoin-fork', symbol: 'btc', name: 'Some Fork' },
    { id: 'ethereum', symbol: 'eth', name: 'Ethereum' },
  ]);
  assert.equal(names.get('BTC'), 'Bitcoin');
  assert.equal(names.get('ETH'), 'Ethereum');
  assert.equal(names.size, 2);
});

test('coingecko: markets give both an asset and a delayed quote', () => {
  const rows = coingecko.parseMarkets([
    {
      id: 'bitcoin',
      symbol: 'btc',
      name: 'Bitcoin',
      current_price: 64000,
      high_24h: 65000,
      low_24h: 63000,
      total_volume: 25_000_000_000,
      price_change_24h: -500,
      price_change_percentage_24h: -0.775,
      last_updated: '2024-05-01T10:00:00.000Z',
    },
  ]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].asset.name, 'Bitcoin');
  assert.equal(rows[0].asset.displaySymbol, 'BTC/USD');
  assert.equal(rows[0].quote.price, 64000);
  assert.equal(rows[0].quote.delayed, true);
  assert.equal(rows[0].quote.ts, Date.parse('2024-05-01T10:00:00.000Z'));
});

/* --------------------------------------------------------------------- misc */

test('toNumber refuses anything that is not a finite number', () => {
  assert.equal(toNumber('12.5'), 12.5);
  assert.equal(toNumber(12.5), 12.5);
  assert.equal(toNumber('0'), 0);
  assert.equal(toNumber(''), null);
  assert.equal(toNumber(null), null);
  assert.equal(toNumber(undefined), null);
  assert.equal(toNumber('abc'), null);
  assert.equal(toNumber(Number.POSITIVE_INFINITY), null);
  assert.equal(toNumber('1e999'), null);
});
