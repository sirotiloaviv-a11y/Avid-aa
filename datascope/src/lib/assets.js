/**
 * The asset registry: what is being watched, and what each thing is called.
 *
 * Names matter more here than usual, because an alert notification has to read
 * "Apple Inc. / AAPL" rather than a bare ticker. Names come from the providers -
 * CoinGecko for crypto, Finnhub or Yahoo for stocks - and are merged in as they
 * resolve.
 *
 * The seed table below exists only so the default watchlist has readable labels
 * before any network call returns. Provider data always overwrites it, and an
 * asset outside the table simply has no name until a provider supplies one. The
 * app never fabricates a name for a symbol it does not recognise.
 */

import { assetKey } from './model.js';

/**
 * Offline fallback labels for the default watchlist only. Overwritten by
 * provider responses as soon as they arrive.
 */
export const SEED_NAMES = Object.freeze({
  BTC: 'Bitcoin',
  ETH: 'Ethereum',
  SOL: 'Solana',
  XRP: 'XRP',
  ADA: 'Cardano',
  DOGE: 'Dogecoin',
  BNB: 'BNB',
  AAPL: 'Apple Inc.',
  MSFT: 'Microsoft Corporation',
  NVDA: 'NVIDIA Corporation',
  TSLA: 'Tesla, Inc.',
  AMZN: 'Amazon.com, Inc.',
  GOOGL: 'Alphabet Inc.',
  META: 'Meta Platforms, Inc.',
});

/** What the dashboard watches on first load. */
export const DEFAULT_WATCHLIST = Object.freeze([
  { provider: 'binance', symbol: 'BTCUSDT', assetClass: 'crypto', base: 'BTC', currency: 'USDT' },
  { provider: 'binance', symbol: 'ETHUSDT', assetClass: 'crypto', base: 'ETH', currency: 'USDT' },
  { provider: 'binance', symbol: 'SOLUSDT', assetClass: 'crypto', base: 'SOL', currency: 'USDT' },
  { provider: 'yahoo', symbol: 'AAPL', assetClass: 'stock', base: 'AAPL', currency: 'USD' },
  { provider: 'yahoo', symbol: 'MSFT', assetClass: 'stock', base: 'MSFT', currency: 'USD' },
  { provider: 'yahoo', symbol: 'NVDA', assetClass: 'stock', base: 'NVDA', currency: 'USD' },
]);

/**
 * @param {{provider: string, symbol: string, assetClass: string, base?: string, currency?: string}} entry
 * @returns {import('./model.js').Asset}
 */
export function buildAsset(entry) {
  const base = entry.base ?? entry.symbol;
  const displaySymbol =
    entry.assetClass === 'crypto' && entry.currency && entry.symbol.endsWith(entry.currency)
      ? `${entry.symbol.slice(0, -entry.currency.length)}/${entry.currency}`
      : entry.symbol;
  return {
    key: assetKey(entry.provider, entry.symbol),
    provider: entry.provider,
    symbol: entry.symbol,
    displaySymbol,
    name: SEED_NAMES[base] ?? null,
    assetClass: entry.assetClass,
    currency: entry.currency ?? null,
    baseAsset: base,
  };
}

export class AssetRegistry {
  constructor() {
    /** @type {Map<string, import('./model.js').Asset>} */
    this.assets = new Map();
    /** @type {Map<string, string>} Ticker code -> resolved name. */
    this.names = new Map();
  }

  /**
   * Inserts or merges an asset. A field already present is only replaced by a
   * non-null value, so a later partial record cannot erase a resolved name.
   * @param {import('./model.js').Asset} asset
   */
  upsert(asset) {
    const existing = this.assets.get(asset.key);
    const merged = existing ? { ...existing } : { ...asset };
    if (existing) {
      for (const [field, value] of Object.entries(asset)) {
        if (value !== null && value !== undefined && value !== '') merged[field] = value;
      }
    }
    if (!merged.name) {
      const resolved = this.names.get(String(merged.baseAsset ?? merged.symbol).toUpperCase());
      if (resolved) merged.name = resolved;
    }
    this.assets.set(asset.key, merged);
    return merged;
  }

  /**
   * Feeds in a batch of ticker-code -> name mappings (CoinGecko's coin list),
   * applying them to assets already registered without a name.
   * @param {Map<string, string>|Record<string, string>} mapping
   */
  addNames(mapping) {
    const entries = mapping instanceof Map ? mapping.entries() : Object.entries(mapping);
    for (const [code, name] of entries) {
      if (typeof name !== 'string' || !name) continue;
      this.names.set(String(code).toUpperCase(), name);
    }
    for (const [key, asset] of this.assets) {
      if (asset.name) continue;
      const resolved = this.names.get(String(asset.baseAsset ?? asset.symbol).toUpperCase());
      if (resolved) this.assets.set(key, { ...asset, name: resolved });
    }
  }

  /** @param {string} key */
  get(key) {
    return this.assets.get(key) ?? null;
  }

  /** @param {string} key */
  has(key) {
    return this.assets.has(key);
  }

  /** @param {string} key */
  delete(key) {
    return this.assets.delete(key);
  }

  list() {
    return [...this.assets.values()];
  }

  /** @param {'crypto'|'stock'} assetClass */
  byClass(assetClass) {
    return this.list().filter((asset) => asset.assetClass === assetClass);
  }

  get size() {
    return this.assets.size;
  }
}

/**
 * Ranked search over assets: exact symbol first, then symbol prefix, then name.
 * Ties keep alphabetical order so the list never reshuffles under the cursor
 * while someone is typing.
 *
 * @param {import('./model.js').Asset[]} assets
 * @param {string} query
 * @param {{limit?: number, assetClass?: string|null}} [options]
 * @returns {import('./model.js').Asset[]}
 */
export function searchAssets(assets, query, options = {}) {
  const limit = options.limit ?? 50;
  const needle = String(query ?? '').trim().toLowerCase();
  const pool = options.assetClass
    ? assets.filter((asset) => asset.assetClass === options.assetClass)
    : assets;

  const sorted = pool
    .slice()
    .sort((a, b) => a.displaySymbol.localeCompare(b.displaySymbol, 'en'));

  if (needle === '') return sorted.slice(0, limit);

  /** @type {[number, import('./model.js').Asset][]} */
  const scored = [];
  for (const asset of sorted) {
    const symbol = asset.symbol.toLowerCase();
    const display = asset.displaySymbol.toLowerCase();
    const name = (asset.name ?? '').toLowerCase();

    let rank = -1;
    if (symbol === needle || display === needle) rank = 0;
    else if (symbol.startsWith(needle) || display.startsWith(needle)) rank = 1;
    else if (name.startsWith(needle)) rank = 2;
    else if (symbol.includes(needle) || display.includes(needle)) rank = 3;
    else if (name.includes(needle)) rank = 4;

    if (rank >= 0) scored.push([rank, asset]);
  }

  return scored
    .sort((a, b) => a[0] - b[0])
    .slice(0, limit)
    .map(([, asset]) => asset);
}

/**
 * The label used wherever both parts must appear - notifications, history rows.
 * @param {import('./model.js').Asset|null} asset
 * @param {string} [fallback]
 */
export function assetLabel(asset, fallback = '') {
  if (!asset) return fallback;
  return asset.name ? `${asset.name} / ${asset.displaySymbol}` : asset.displaySymbol;
}
