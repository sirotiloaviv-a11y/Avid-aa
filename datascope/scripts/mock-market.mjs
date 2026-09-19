/**
 * A local market feed that speaks the real providers' wire formats.
 *
 * The browser tests need prices that move on command: an alert for "BTC above
 * 70,000" can only be verified by making BTC cross 70,000 at a known moment.
 * Waiting for a live market to do that is not a test. This server emits exactly
 * the frames Binance, Finnhub, Yahoo and CoinGecko emit, so the app's parsers,
 * reconnection logic and alert engine run unmodified against it.
 *
 * It is also how the app can be demonstrated without any network access at all.
 *
 * Endpoints
 *   ws   /binance/stream?streams=btcusdt@ticker/btcusdt@kline_1m
 *   ws   /finnhub/ws?token=...
 *   GET  /binance/api/v3/exchangeInfo | /ticker/24hr | /klines
 *   GET  /yahoo/v8/finance/chart/<symbol>
 *   GET  /coingecko/coins/list | /coins/markets
 *   POST /control/price   {"symbol":"BTCUSDT","price":70123.45}
 *   POST /control/spike   {"symbol":"BTCUSDT","percent":5}
 *   POST /control/volume  {"symbol":"BTCUSDT","multiple":8}
 *   GET  /control/state
 *
 * Usage: node scripts/mock-market.mjs [--port 4500] [--quiet]
 */

import http from 'node:http';

import { attachWebSocket } from './ws-lite.mjs';

const args = process.argv.slice(2);
const portIndex = args.indexOf('--port');
const PORT = portIndex !== -1 && args[portIndex + 1] ? Number(args[portIndex + 1]) : 4500;
const QUIET = args.includes('--quiet');
const TICK_MS = 500;

/** Deterministic seeds so a failing test reproduces exactly. */
const INSTRUMENTS = [
  { symbol: 'BTCUSDT', base: 'BTC', quote: 'USDT', name: 'Bitcoin', price: 64000, vol: 0.0012, volume: 900, class: 'crypto' },
  { symbol: 'ETHUSDT', base: 'ETH', quote: 'USDT', name: 'Ethereum', price: 3200, vol: 0.0016, volume: 5400, class: 'crypto' },
  { symbol: 'SOLUSDT', base: 'SOL', quote: 'USDT', name: 'Solana', price: 145, vol: 0.0025, volume: 42000, class: 'crypto' },
  { symbol: 'AAPL', base: 'AAPL', quote: 'USD', name: 'Apple Inc.', price: 228.5, vol: 0.0006, volume: 1200, class: 'stock' },
  { symbol: 'MSFT', base: 'MSFT', quote: 'USD', name: 'Microsoft Corporation', price: 415.2, vol: 0.0005, volume: 800, class: 'stock' },
  { symbol: 'NVDA', base: 'NVDA', quote: 'USD', name: 'NVIDIA Corporation', price: 121.4, vol: 0.0018, volume: 6400, class: 'stock' },
];

/** mulberry32 - the same generator the rest of the project uses. */
function createRandom(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6d2b_79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

const random = createRandom(0x0da7a5c0);

/** @type {Map<string, any>} */
const state = new Map();
for (const instrument of INSTRUMENTS) {
  state.set(instrument.symbol, {
    ...instrument,
    open: instrument.price,
    prevClose: instrument.price,
    high: instrument.price,
    low: instrument.price,
    lastVolume: instrument.volume,
    candles: seedCandles(instrument),
    /** Set by /control/volume for the next few ticks. */
    volumeBoost: 1,
    volumeBoostTicks: 0,
  });
}

function seedCandles(instrument) {
  const candles = [];
  const now = Date.now();
  const start = Math.floor((now - 120 * 60_000) / 60_000) * 60_000;
  let price = instrument.price;
  for (let i = 0; i < 120; i += 1) {
    const open = price;
    price = round(price * (1 + (random() * 2 - 1) * instrument.vol), instrument.price);
    candles.push({
      t: start + i * 60_000,
      open,
      high: Math.max(open, price),
      low: Math.min(open, price),
      close: price,
      volume: Math.round(instrument.volume * (0.7 + random() * 0.6)),
    });
  }
  return candles;
}

function round(value, reference) {
  const digits = reference >= 1000 ? 2 : reference >= 1 ? 2 : 6;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** One price step for every instrument, plus candle upkeep. */
function tick() {
  const now = Date.now();
  for (const entry of state.values()) {
    const drift = (random() * 2 - 1) * entry.vol;
    entry.price = Math.max(0.000001, round(entry.price * (1 + drift), entry.price));
    if (entry.price > entry.high) entry.high = entry.price;
    if (entry.price < entry.low) entry.low = entry.price;

    let volume = entry.volume * (0.7 + random() * 0.6) * (TICK_MS / 60_000);
    if (entry.volumeBoostTicks > 0) {
      volume *= entry.volumeBoost;
      entry.volumeBoostTicks -= 1;
    }
    entry.lastVolume = volume;

    const bucket = Math.floor(now / 60_000) * 60_000;
    const last = entry.candles[entry.candles.length - 1];
    if (last && last.t === bucket) {
      last.close = entry.price;
      last.high = Math.max(last.high, entry.price);
      last.low = Math.min(last.low, entry.price);
      last.volume += volume;
    } else {
      entry.candles.push({
        t: bucket,
        open: entry.price,
        high: entry.price,
        low: entry.price,
        close: entry.price,
        volume,
      });
      if (entry.candles.length > 240) entry.candles.shift();
    }
  }
  broadcast();
}

/* ------------------------------------------------------------- wire formats */

function binanceTickerFrame(entry) {
  const changeAbs = entry.price - entry.open;
  return {
    e: '24hrTicker',
    E: Date.now(),
    s: entry.symbol,
    p: changeAbs.toFixed(8),
    P: (entry.open > 0 ? (changeAbs / entry.open) * 100 : 0).toFixed(3),
    w: entry.price.toFixed(8),
    x: entry.prevClose.toFixed(8),
    c: entry.price.toFixed(8),
    Q: '1.00000000',
    b: (entry.price * 0.9999).toFixed(8),
    B: '1.00000000',
    a: (entry.price * 1.0001).toFixed(8),
    A: '1.00000000',
    o: entry.open.toFixed(8),
    h: entry.high.toFixed(8),
    l: entry.low.toFixed(8),
    v: totalVolume(entry).toFixed(8),
    q: (totalVolume(entry) * entry.price).toFixed(8),
    O: Date.now() - 86_400_000,
    C: Date.now(),
    F: 0,
    L: 1000,
    n: 1000,
  };
}

function binanceKlineFrame(entry) {
  const candle = entry.candles[entry.candles.length - 1];
  return {
    e: 'kline',
    E: Date.now(),
    s: entry.symbol,
    k: {
      t: candle.t,
      T: candle.t + 59_999,
      s: entry.symbol,
      i: '1m',
      f: 0,
      L: 100,
      o: candle.open.toFixed(8),
      c: candle.close.toFixed(8),
      h: candle.high.toFixed(8),
      l: candle.low.toFixed(8),
      v: candle.volume.toFixed(8),
      n: 100,
      x: false,
      q: (candle.volume * candle.close).toFixed(8),
      V: (candle.volume / 2).toFixed(8),
      Q: ((candle.volume / 2) * candle.close).toFixed(8),
      B: '0',
    },
  };
}

function finnhubTradeFrame(entries) {
  return {
    type: 'trade',
    data: entries.map((entry) => ({
      s: entry.symbol,
      p: entry.price,
      t: Date.now(),
      v: Math.round(entry.lastVolume),
    })),
  };
}

function totalVolume(entry) {
  return entry.candles.reduce((sum, candle) => sum + candle.volume, 0);
}

/* -------------------------------------------------------------- connections */

/** @type {Set<{connection: any, kind: string, streams: Set<string>, symbols: Set<string>}>} */
const clients = new Set();

function broadcast() {
  for (const client of clients) {
    if (client.connection.closed) {
      clients.delete(client);
      continue;
    }
    if (client.kind === 'binance') {
      for (const stream of client.streams) {
        const [rawSymbol, channel] = stream.split('@');
        const entry = state.get(rawSymbol.toUpperCase());
        if (!entry) continue;
        const data =
          channel === 'ticker'
            ? binanceTickerFrame(entry)
            : channel?.startsWith('kline')
              ? binanceKlineFrame(entry)
              : null;
        if (!data) continue;
        client.connection.send(JSON.stringify({ stream, data }));
      }
    } else if (client.kind === 'finnhub') {
      const entries = [...client.symbols].map((symbol) => state.get(symbol)).filter(Boolean);
      if (entries.length > 0) client.connection.send(JSON.stringify(finnhubTradeFrame(entries)));
    }
  }
}

/* --------------------------------------------------------------- http layer */

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    // The app is served from a different local port, so the mock has to allow it
    // explicitly - exactly as the real providers do.
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'content-type',
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readBody(request) {
  return new Promise((resolve) => {
    let body = '';
    request.on('data', (chunk) => {
      body += chunk;
      if (body.length > 10_000) request.destroy();
    });
    request.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        resolve({});
      }
    });
  });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', `http://127.0.0.1:${PORT}`);
  const path = url.pathname;

  if (request.method === 'OPTIONS') {
    response.writeHead(204, {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
    });
    response.end();
    return;
  }

  /* ---- control ---- */
  if (path === '/control/price' && request.method === 'POST') {
    const body = await readBody(request);
    const entry = state.get(String(body.symbol ?? '').toUpperCase());
    if (!entry) return sendJson(response, 404, { error: 'unknown symbol' });
    entry.price = Number(body.price);
    entry.high = Math.max(entry.high, entry.price);
    entry.low = Math.min(entry.low, entry.price);
    const candle = entry.candles[entry.candles.length - 1];
    if (candle) {
      candle.close = entry.price;
      candle.high = Math.max(candle.high, entry.price);
      candle.low = Math.min(candle.low, entry.price);
    }
    broadcast();
    return sendJson(response, 200, { ok: true, symbol: entry.symbol, price: entry.price });
  }

  if (path === '/control/spike' && request.method === 'POST') {
    const body = await readBody(request);
    const entry = state.get(String(body.symbol ?? '').toUpperCase());
    if (!entry) return sendJson(response, 404, { error: 'unknown symbol' });
    entry.price = round(entry.price * (1 + Number(body.percent ?? 0) / 100), entry.price);
    entry.high = Math.max(entry.high, entry.price);
    entry.low = Math.min(entry.low, entry.price);
    broadcast();
    return sendJson(response, 200, { ok: true, symbol: entry.symbol, price: entry.price });
  }

  if (path === '/control/volume' && request.method === 'POST') {
    const body = await readBody(request);
    const entry = state.get(String(body.symbol ?? '').toUpperCase());
    if (!entry) return sendJson(response, 404, { error: 'unknown symbol' });
    entry.volumeBoost = Number(body.multiple ?? 5);
    entry.volumeBoostTicks = Number(body.ticks ?? 20);
    return sendJson(response, 200, { ok: true, symbol: entry.symbol, boost: entry.volumeBoost });
  }

  if (path === '/control/state') {
    return sendJson(
      response,
      200,
      [...state.values()].map((entry) => ({
        symbol: entry.symbol,
        price: entry.price,
        open: entry.open,
        high: entry.high,
        low: entry.low,
      })),
    );
  }

  /* ---- binance rest ---- */
  if (path === '/binance/api/v3/exchangeInfo') {
    return sendJson(response, 200, {
      symbols: [...state.values()]
        .filter((entry) => entry.class === 'crypto')
        .map((entry) => ({
          symbol: entry.symbol,
          status: 'TRADING',
          baseAsset: entry.base,
          quoteAsset: entry.quote,
        })),
    });
  }

  if (path === '/binance/api/v3/ticker/24hr') {
    const rows = [...state.values()]
      .filter((entry) => entry.class === 'crypto')
      .map((entry) => {
        const changeAbs = entry.price - entry.open;
        return {
          symbol: entry.symbol,
          priceChange: changeAbs.toFixed(8),
          priceChangePercent: (entry.open > 0 ? (changeAbs / entry.open) * 100 : 0).toFixed(3),
          lastPrice: entry.price.toFixed(8),
          openPrice: entry.open.toFixed(8),
          prevClosePrice: entry.prevClose.toFixed(8),
          highPrice: entry.high.toFixed(8),
          lowPrice: entry.low.toFixed(8),
          volume: totalVolume(entry).toFixed(8),
          quoteVolume: (totalVolume(entry) * entry.price).toFixed(8),
          closeTime: Date.now(),
        };
      });
    return sendJson(response, 200, rows);
  }

  if (path === '/binance/api/v3/klines') {
    const symbol = String(url.searchParams.get('symbol') ?? '').toUpperCase();
    const entry = state.get(symbol);
    if (!entry) return sendJson(response, 400, { code: -1121, msg: 'Invalid symbol.' });
    const limit = Number(url.searchParams.get('limit') ?? 240);
    const rows = entry.candles.slice(-limit).map((candle) => [
      candle.t,
      candle.open.toFixed(8),
      candle.high.toFixed(8),
      candle.low.toFixed(8),
      candle.close.toFixed(8),
      candle.volume.toFixed(8),
      candle.t + 59_999,
      (candle.volume * candle.close).toFixed(8),
      100,
      '0',
      '0',
      '0',
    ]);
    return sendJson(response, 200, rows);
  }

  /* ---- finnhub rest ---- */
  if (path === '/finnhub/quote') {
    const entry = state.get(String(url.searchParams.get('symbol') ?? '').toUpperCase());
    if (!entry) return sendJson(response, 200, { c: 0, d: null, dp: null, h: 0, l: 0, o: 0, pc: 0, t: 0 });
    return sendJson(response, 200, {
      c: entry.price,
      d: entry.price - entry.prevClose,
      dp: ((entry.price - entry.prevClose) / entry.prevClose) * 100,
      h: entry.high,
      l: entry.low,
      o: entry.open,
      pc: entry.prevClose,
      t: Math.floor(Date.now() / 1000),
    });
  }

  if (path === '/finnhub/search') {
    const query = String(url.searchParams.get('q') ?? '').toUpperCase();
    const rows = [...state.values()]
      .filter((entry) => entry.class === 'stock' && (entry.symbol.includes(query) || entry.name.toUpperCase().includes(query)))
      .map((entry) => ({
        description: entry.name.toUpperCase(),
        displaySymbol: entry.symbol,
        symbol: entry.symbol,
        type: 'Common Stock',
      }));
    return sendJson(response, 200, { count: rows.length, result: rows });
  }

  if (path === '/finnhub/stock/profile2') {
    const entry = state.get(String(url.searchParams.get('symbol') ?? '').toUpperCase());
    if (!entry) return sendJson(response, 200, {});
    return sendJson(response, 200, { name: entry.name, ticker: entry.symbol, currency: 'USD' });
  }

  /* ---- yahoo ---- */
  if (path.startsWith('/yahoo/v8/finance/chart/')) {
    const symbol = decodeURIComponent(path.slice('/yahoo/v8/finance/chart/'.length)).toUpperCase();
    const entry = state.get(symbol);
    if (!entry) {
      return sendJson(response, 404, {
        chart: { result: null, error: { code: 'Not Found', description: `No data found, symbol may be delisted` } },
      });
    }
    const candles = entry.candles.slice(-120);
    return sendJson(response, 200, {
      chart: {
        result: [
          {
            meta: {
              currency: 'USD',
              symbol: entry.symbol,
              exchangeName: 'NMS',
              longName: entry.name,
              shortName: entry.name,
              regularMarketPrice: entry.price,
              chartPreviousClose: entry.prevClose,
              regularMarketDayHigh: entry.high,
              regularMarketDayLow: entry.low,
              regularMarketDayOpen: entry.open,
              regularMarketVolume: Math.round(totalVolume(entry)),
              regularMarketTime: Math.floor(Date.now() / 1000),
            },
            timestamp: candles.map((candle) => Math.floor(candle.t / 1000)),
            indicators: {
              quote: [
                {
                  open: candles.map((candle) => candle.open),
                  high: candles.map((candle) => candle.high),
                  low: candles.map((candle) => candle.low),
                  close: candles.map((candle) => candle.close),
                  volume: candles.map((candle) => Math.round(candle.volume)),
                },
              ],
            },
          },
        ],
        error: null,
      },
    });
  }

  /* ---- coingecko ---- */
  if (path === '/coingecko/coins/list') {
    return sendJson(
      response,
      200,
      [...state.values()]
        .filter((entry) => entry.class === 'crypto')
        .map((entry) => ({ id: entry.name.toLowerCase(), symbol: entry.base.toLowerCase(), name: entry.name })),
    );
  }

  if (path === '/coingecko/coins/markets') {
    return sendJson(
      response,
      200,
      [...state.values()]
        .filter((entry) => entry.class === 'crypto')
        .map((entry) => ({
          id: entry.name.toLowerCase(),
          symbol: entry.base.toLowerCase(),
          name: entry.name,
          current_price: entry.price,
          high_24h: entry.high,
          low_24h: entry.low,
          total_volume: Math.round(totalVolume(entry) * entry.price),
          price_change_24h: entry.price - entry.open,
          price_change_percentage_24h: ((entry.price - entry.open) / entry.open) * 100,
          last_updated: new Date().toISOString(),
        })),
    );
  }

  sendJson(response, 404, { error: 'not found', path });
});

attachWebSocket(server, (connection) => {
  const path = connection.url.pathname;

  if (path === '/binance/stream') {
    const streams = new Set((connection.url.searchParams.get('streams') ?? '').split('/').filter(Boolean));
    const client = { connection, kind: 'binance', streams, symbols: new Set() };
    clients.add(client);
    connection.onClose(() => clients.delete(client));
    if (!QUIET) console.log(`[mock] binance client: ${[...streams].join(', ')}`);
    broadcast();
    return;
  }

  if (path === '/finnhub/ws') {
    const client = { connection, kind: 'finnhub', streams: new Set(), symbols: new Set() };
    clients.add(client);
    connection.onClose(() => clients.delete(client));
    connection.onMessage((text) => {
      try {
        const message = JSON.parse(text);
        if (message.type === 'subscribe' && typeof message.symbol === 'string') {
          client.symbols.add(message.symbol.toUpperCase());
          if (!QUIET) console.log(`[mock] finnhub subscribe: ${message.symbol}`);
        } else if (message.type === 'unsubscribe') {
          client.symbols.delete(String(message.symbol).toUpperCase());
        }
      } catch {
        /* ignore malformed client frames */
      }
    });
    return;
  }

  connection.close();
});

const timer = setInterval(tick, TICK_MS);
timer.unref?.();

server.listen(PORT, '127.0.0.1', () => {
  if (QUIET) return;
  console.log(`mock market listening on http://127.0.0.1:${PORT}`);
  console.log(`  binance ws : ws://127.0.0.1:${PORT}/binance/stream?streams=btcusdt@ticker`);
  console.log(`  finnhub ws : ws://127.0.0.1:${PORT}/finnhub/ws`);
  console.log(`  control    : POST /control/price {"symbol":"BTCUSDT","price":70000}`);
});

export { server, state };
