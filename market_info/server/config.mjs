// Reads settings from environment variables, then from market_info/.env.
// The .env file is ignored by Git; .env.example documents every setting.
import { existsSync, readFileSync } from 'node:fs';

export const STOCK_SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;
export const CRYPTO_TICKER_RE = /^[A-Z0-9]{1,10}$/;
export const COINGECKO_ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function parseEnvFile(text) {
  const out = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 1) continue;
    let value = line.slice(eq + 1).trim();
    if (/^(['"]).*\1$/.test(value)) value = value.slice(1, -1);
    out[line.slice(0, eq).trim()] = value;
  }
  return out;
}

// "AAPL=Apple, MSFT" -> [{ key: 'AAPL', value: 'Apple' }, { key: 'MSFT', value: '' }]
export function parseList(text) {
  return String(text ?? '').split(',').map((s) => s.trim()).filter(Boolean).map((item) => {
    const eq = item.indexOf('=');
    return eq < 0 ? { key: item, value: '' } : { key: item.slice(0, eq).trim(), value: item.slice(eq + 1).trim() };
  });
}

export const DEFAULTS = {
  MARKET_STOCK_SYMBOLS: 'AAPL=Apple,MSFT=Microsoft,NVDA=NVIDIA,SPY=SPDR S&P 500 ETF',
  MARKET_CRYPTO_ASSETS: 'BTC=bitcoin,ETH=ethereum,SOL=solana',
  ALPHA_VANTAGE_BASE_URL: 'https://www.alphavantage.co/query',
  ALPHA_VANTAGE_DAILY_LIMIT: '25',
  ALPHA_VANTAGE_PER_MINUTE: '5',
  COINGECKO_BASE_URL: 'https://api.coingecko.com/api/v3',
  COINGECKO_PER_MINUTE: '30',
  COINGECKO_MONTHLY_LIMIT: '10000',
  STOCK_CACHE_MINUTES: '360',
  CRYPTO_QUOTE_CACHE_SECONDS: '120',
  CRYPTO_HISTORY_CACHE_MINUTES: '60',
  REQUEST_TIMEOUT_SECONDS: '10',
};

export function loadConfig({ env = process.env, envFile = null } = {}) {
  const fileVars = envFile && existsSync(envFile) ? parseEnvFile(readFileSync(envFile, 'utf8')) : {};
  const get = (k) => {
    const v = env[k] ?? fileVars[k];
    return v === undefined || v === '' ? DEFAULTS[k] ?? '' : v;
  };
  const num = (k) => {
    const n = Number(get(k));
    return Number.isFinite(n) && n > 0 ? n : Number(DEFAULTS[k]);
  };
  const warnings = [];

  const stocks = [];
  for (const { key, value } of parseList(get('MARKET_STOCK_SYMBOLS'))) {
    const symbol = key.toUpperCase();
    if (!STOCK_SYMBOL_RE.test(symbol)) { warnings.push(`סימול מניה לא תקין הושמט: ${key}`); continue; }
    stocks.push({ symbol, name: value || symbol });
  }
  const crypto = [];
  for (const { key, value } of parseList(get('MARKET_CRYPTO_ASSETS'))) {
    const symbol = key.toUpperCase();
    if (!CRYPTO_TICKER_RE.test(symbol) || !COINGECKO_ID_RE.test(value)) {
      warnings.push(`נכס קריפטו לא תקין הושמט: ${key}=${value}`);
      continue;
    }
    crypto.push({ symbol, id: value });
  }

  const timeoutMs = num('REQUEST_TIMEOUT_SECONDS') * 1000;
  return {
    alphaVantage: {
      apiKey: get('ALPHA_VANTAGE_API_KEY'),
      baseUrl: get('ALPHA_VANTAGE_BASE_URL'),
      perDay: num('ALPHA_VANTAGE_DAILY_LIMIT'),
      perMinute: num('ALPHA_VANTAGE_PER_MINUTE'),
      timeoutMs,
    },
    coinGecko: {
      apiKey: get('COINGECKO_DEMO_API_KEY'),
      baseUrl: get('COINGECKO_BASE_URL'),
      perMinute: num('COINGECKO_PER_MINUTE'),
      perMonth: num('COINGECKO_MONTHLY_LIMIT'),
      timeoutMs,
    },
    ttl: {
      stockMs: num('STOCK_CACHE_MINUTES') * 60000,
      cryptoQuoteMs: num('CRYPTO_QUOTE_CACHE_SECONDS') * 1000,
      cryptoHistoryMs: num('CRYPTO_HISTORY_CACHE_MINUTES') * 60000,
    },
    stocks,
    crypto,
    warnings,
  };
}
