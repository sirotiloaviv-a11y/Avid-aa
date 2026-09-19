/**
 * DataScope controller: connect the feeds, keep one state object, render from it.
 *
 * The shape of the app is a loop:
 *   provider frame -> parse -> MarketStore -> (render | alert engine)
 *
 * Two loops run on timers rather than on every frame, because a busy pair sends
 * several messages a second and neither the DOM nor the alert engine needs to
 * see all of them:
 *   - rendering is coalesced into one requestAnimationFrame per burst,
 *   - the alert engine runs on a fixed 1s tick, which also gives time-window
 *     rules a predictable cadence.
 *
 * Alert rules, history and settings persist in localStorage. Nothing is sent
 * anywhere except to the market data providers themselves.
 */

import { CONNECTION, assetKey } from './lib/model.js';
import { MarketStore, intradayStats, topMovers } from './lib/market.js';
import { AssetRegistry, DEFAULT_WATCHLIST, buildAsset, searchAssets } from './lib/assets.js';
import { AlertHistory, RULE_TYPE, createRule, runAlertEngine, validateRule } from './lib/alerts.js';
import { configFromSearch, resolveProviders } from './lib/config.js';
import { KEYS, clearAll, loadSettings, readJson, saveSettings, writeJson } from './lib/storage.js';
import { buildHistoryCsv, safeFileName } from './lib/exporters.js';
import { formatAge, formatClock, todayIso } from './lib/format.js';
import { byId, clear, downloadText, el, show } from './ui/dom.js';
import { renderPriceChart, renderVolumeChart } from './ui/charts.js';
import { renderConnectionPills, renderIntradayStats, renderWatchCards } from './ui/dashboard.js';
import { renderTicker } from './ui/ticker.js';
import { fillAssetOptions, renderHistory, renderRules, showRuleErrors } from './ui/alerts-ui.js';
import { Notifier, PERMISSION } from './ui/notifications.js';

import * as binance from './providers/binance.js';
import * as finnhub from './providers/finnhub.js';
import * as yahoo from './providers/yahoo.js';
import * as coingecko from './providers/coingecko.js';
import { PollingSource, ReconnectingSocket } from './providers/connection.js';

const ALERT_TICK_MS = 1_000;

const state = {
  config: null,
  settings: null,
  market: new MarketStore(),
  /** The searchable universe, which is larger than the watchlist. */
  universe: new AssetRegistry(),
  /** @type {import('./lib/alerts.js').AlertRule[]} */
  rules: [],
  history: new AlertHistory(200),
  /** @type {Record<string, string|null>} */
  diagnostics: {},
  selectedKey: null,
  searchResults: [],
  searchIndex: -1,
  classFilter: 'all',
  /** @type {{asset: any, quote: any}[]} */
  movers: [],
  sources: {
    crypto: { id: 'crypto', label: 'קריפטו', status: CONNECTION.IDLE, detail: '', silenceMs: null, stale: false },
    stock: { id: 'stock', label: 'מניות', status: CONNECTION.IDLE, detail: '', silenceMs: null, stale: false },
  },
};

const ui = {};
const connections = { cryptoSocket: null, stockSocket: null, stockPoll: null, moversPoll: null };
let notifier = null;
let renderQueued = false;

/* ------------------------------------------------------------------ helpers */

function cacheElements() {
  const ids = [
    'ticker',
    'connection-pills',
    'enable-notifications',
    'toggle-sound',
    'toggle-settings',
    'settings-panel',
    'finnhub-token',
    'save-token',
    'clear-token',
    'clear-storage',
    'settings-status',
    'asset-search',
    'asset-results',
    'class-filter',
    'watch-cards',
    'detail-name',
    'detail-symbol',
    'detail-source',
    'intraday-stats',
    'price-chart',
    'price-tooltip',
    'volume-chart',
    'volume-tooltip',
    'chart-readout',
    'chart-empty',
    'notification-state',
    'rule-form',
    'rule-asset',
    'rule-type',
    'rule-window',
    'rule-cooldown',
    'rule-form-status',
    'rule-list',
    'history-list',
    'export-history',
    'clear-history',
    'toast-stack',
  ];
  for (const id of ids) ui[id] = byId(id);
}

/** Coalesces render requests into one frame. */
function requestRender() {
  if (renderQueued) return;
  renderQueued = true;
  const schedule = globalThis.requestAnimationFrame ?? ((fn) => setTimeout(fn, 16));
  schedule(() => {
    renderQueued = false;
    render();
  });
}

function isCompact() {
  return Boolean(globalThis.matchMedia?.('(max-width: 720px)')?.matches);
}

/** @param {string} url */
async function getJson(url, { signal } = {}) {
  const response = await fetch(url, { signal, headers: { accept: 'application/json' } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} מ־${new URL(url, location.href).host || 'השרת המקומי'}`);
  }
  return response.json();
}

/* --------------------------------------------------------------- connectors */

function cryptoSymbols() {
  return state.market
    .watchlist()
    .filter((asset) => asset.provider === 'binance')
    .map((asset) => asset.symbol);
}

function stockSymbols() {
  return state.market
    .watchlist()
    .filter((asset) => asset.assetClass === 'stock')
    .map((asset) => asset.symbol);
}

function setSourceStatus(id, status, detail) {
  const source = state.sources[id];
  source.status = status;
  source.detail = detail ?? '';
  requestRender();
}

function connectCrypto() {
  connections.cryptoSocket?.close();
  const symbols = cryptoSymbols();
  if (symbols.length === 0) {
    connections.cryptoSocket = null;
    setSourceStatus('crypto', CONNECTION.IDLE, 'אין נכסי קריפטו במעקב');
    return;
  }

  connections.cryptoSocket = new ReconnectingSocket({
    url: () => binance.streamUrl(cryptoSymbols(), { ws: state.config.binanceWs }),
    onStatus: (status, detail) => setSourceStatus('crypto', status, detail),
    onMessage: (text) => {
      const parsed = binance.parseSocketMessage(text);
      if (!parsed) return;
      if (parsed.kind === 'quote') {
        state.market.applyQuote(parsed.quote);
      } else if (parsed.kind === 'candle') {
        state.market.applyCandle(parsed.key, parsed.candle);
      }
      requestRender();
    },
  });
  connections.cryptoSocket.open();
  backfillCrypto(symbols);
}

/** Seeds the chart so it is not empty for the first minutes after a reload. */
async function backfillCrypto(symbols) {
  for (const symbol of symbols) {
    try {
      const payload = await getJson(
        binance.endpoints.klines(symbol, '1m', 240, state.config.binanceRest),
      );
      const candles = binance.parseRestKlines(payload);
      if (candles.length > 0) state.market.seedSeries(assetKey('binance', symbol), candles);
      requestRender();
    } catch {
      // A failed backfill is not fatal: the live stream fills the chart in.
    }
  }
}

function connectStocks() {
  connections.stockSocket?.close();
  connections.stockPoll?.stop();
  connections.stockSocket = null;
  connections.stockPoll = null;

  const symbols = stockSymbols();
  if (symbols.length === 0) {
    setSourceStatus('stock', CONNECTION.IDLE, 'אין מניות במעקב');
    return;
  }

  const providers = resolveProviders({ finnhubToken: state.settings.finnhubToken });

  if (providers.stock === 'finnhub') {
    const token = state.settings.finnhubToken;
    connections.stockSocket = new ReconnectingSocket({
      url: () => finnhub.socketUrl(token, state.config.finnhubWs),
      onStatus: (status, detail) => setSourceStatus('stock', status, detail),
      onOpen: (socket) => {
        for (const symbol of stockSymbols()) socket.send(finnhub.subscribeMessage(symbol));
      },
      onMessage: (text) => {
        const parsed = finnhub.parseSocketMessage(text);
        if (!parsed) return;
        if (parsed.kind === 'trades') {
          for (const trade of parsed.trades) state.market.applyTrade(trade);
          requestRender();
        } else if (parsed.kind === 'error') {
          setSourceStatus('stock', CONNECTION.ERROR, parsed.message);
        }
      },
    });
    connections.stockSocket.open();
    // The trade stream carries no day open, so one REST quote per symbol seeds
    // the day-change figures the cards show.
    seedFinnhubQuotes(symbols, token);
    return;
  }

  connections.stockPoll = new PollingSource({
    intervalMs: state.config.stockPollMs,
    onStatus: (status, detail) => setSourceStatus('stock', status, detail),
    poll: async () => {
      for (const symbol of stockSymbols()) {
        const payload = await getJson(
          yahoo.endpoints.chart(symbol, { rest: state.config.yahooRest }),
        );
        const error = yahoo.parseChartError(payload);
        if (error) throw new Error(error);

        const quote = yahoo.parseChartQuote(payload);
        if (quote) state.market.applyQuote(quote);

        const candles = yahoo.parseChartCandles(payload);
        if (candles.length > 0) state.market.seedSeries(assetKey('yahoo', symbol), candles);

        const meta = yahoo.parseChartAsset(payload);
        if (meta?.name) {
          state.market.registry.upsert({
            ...buildAsset({ provider: 'yahoo', symbol, assetClass: 'stock', currency: meta.currency ?? 'USD' }),
            name: meta.name,
          });
        }
      }
      requestRender();
    },
  });
  connections.stockPoll.start();
}

async function seedFinnhubQuotes(symbols, token) {
  for (const symbol of symbols) {
    try {
      const payload = await getJson(finnhub.endpoints.quote(symbol, token, state.config.finnhubRest));
      const quote = finnhub.parseQuote(symbol, payload);
      if (quote) state.market.applyQuote(quote);

      const profile = await getJson(
        finnhub.endpoints.profile(symbol, token, state.config.finnhubRest),
      );
      const parsed = finnhub.parseProfile(profile);
      if (parsed.name) {
        state.market.registry.upsert({
          ...buildAsset({ provider: 'finnhub', symbol, assetClass: 'stock', currency: parsed.currency ?? 'USD' }),
          name: parsed.name,
        });
      }
      requestRender();
    } catch {
      // Quotes will still arrive over the socket; only the day-open is missing.
    }
  }
}

/** The ticker bar: biggest movers across crypto, refreshed on its own slow loop. */
function startMoversPoll() {
  connections.moversPoll?.stop();
  connections.moversPoll = new PollingSource({
    intervalMs: state.config.moversPollMs,
    poll: async () => {
      const payload = await getJson(binance.endpoints.tickers(null, state.config.binanceRest));
      const quotes = binance.parseRestTickers(payload);
      const rows = [];
      for (const quote of quotes) {
        const asset = state.universe.get(quote.key) ?? state.market.registry.get(quote.key);
        // Only pairs quoted in USDT, or the list is dominated by the same coin
        // priced against a dozen different quote currencies.
        if (!asset || asset.currency !== 'USDT') continue;
        rows.push({ asset, quote });
      }
      state.movers = topMovers(rows, { limit: 14 });
      requestRender();
    },
  });
  connections.moversPoll.start();
}

/** One-time loads: the tradable universe and the crypto name table. */
async function loadUniverse() {
  try {
    const payload = await getJson(binance.endpoints.exchangeInfo(state.config.binanceRest));
    const assets = binance.parseExchangeInfo(payload, { quoteAssets: ['USDT', 'USDC'] });
    for (const asset of assets) state.universe.upsert(asset);
  } catch {
    // Search then falls back to whatever is already on the watchlist.
  }

  try {
    const payload = await getJson(coingecko.endpoints.coinList(state.config.coingeckoRest));
    const names = coingecko.parseCoinList(payload);
    state.universe.addNames(names);
    state.market.registry.addNames(names);
  } catch {
    // Names stay unresolved; the UI shows symbols alone rather than guesses.
  }
  requestRender();
}

/* ------------------------------------------------------------------- search */

let searchTimer = null;

function onSearchInput() {
  const query = ui['asset-search'].value.trim();
  const classFilter = state.classFilter === 'all' ? null : state.classFilter;

  state.searchResults = searchAssets(
    [...state.universe.list(), ...state.market.watchlist()],
    query,
    { assetClass: classFilter, limit: 12 },
  );
  state.searchIndex = -1;
  renderSearchResults();

  // Remote stock search is debounced: it is a network call per keystroke
  // otherwise, against a free tier.
  if (searchTimer) clearTimeout(searchTimer);
  if (query.length >= 2 && state.classFilter !== 'crypto') {
    searchTimer = setTimeout(() => searchStocks(query), 300);
  }
}

async function searchStocks(query) {
  try {
    const token = state.settings.finnhubToken;
    const assets = token
      ? finnhub.parseSearch(
          await getJson(finnhub.endpoints.search(query, token, state.config.finnhubRest)),
        )
      : yahoo.parseSearch(
          await getJson(yahoo.endpoints.search(query, { rest: state.config.yahooRest })),
        );

    for (const asset of assets) state.universe.upsert(asset);
    if (ui['asset-search'].value.trim() === query) onSearchInput();
  } catch {
    // Local results stand.
  }
}

function renderSearchResults() {
  const list = ui['asset-results'];
  clear(list);

  if (state.searchResults.length === 0) {
    show(list, false);
    ui['asset-search'].setAttribute('aria-expanded', 'false');
    return;
  }

  state.searchResults.forEach((asset, index) => {
    const item = el('li', { attrs: { role: 'none' } });
    const button = el('button', {
      class: `asset-option${index === state.searchIndex ? ' is-active' : ''}`,
      attrs: { type: 'button', role: 'option', 'aria-selected': index === state.searchIndex ? 'true' : 'false' },
    });
    button.append(el('span', { class: 'asset-option-symbol', text: asset.displaySymbol, attrs: { dir: 'ltr' } }));
    button.append(el('span', { class: 'asset-option-name', text: asset.name ?? '—' }));
    button.append(
      el('span', {
        class: `asset-chip chip-${asset.assetClass}`,
        text: asset.assetClass === 'crypto' ? 'קריפטו' : 'מניה',
      }),
    );
    button.addEventListener('click', () => addToWatchlist(asset));
    item.append(button);
    list.append(item);
  });

  show(list, true);
  ui['asset-search'].setAttribute('aria-expanded', 'true');
}

function onSearchKeydown(event) {
  if (state.searchResults.length === 0) return;
  switch (event.key) {
    case 'ArrowDown':
      state.searchIndex = Math.min(state.searchResults.length - 1, state.searchIndex + 1);
      break;
    case 'ArrowUp':
      state.searchIndex = Math.max(0, state.searchIndex - 1);
      break;
    case 'Enter':
      if (state.searchIndex >= 0) {
        addToWatchlist(state.searchResults[state.searchIndex]);
        event.preventDefault();
      }
      return;
    case 'Escape':
      state.searchResults = [];
      renderSearchResults();
      return;
    default:
      return;
  }
  event.preventDefault();
  renderSearchResults();
}

/* ---------------------------------------------------------------- watchlist */

function addToWatchlist(asset) {
  if (!asset) return;
  const added = state.market.watch(asset);
  state.selectedKey = added.key;
  ui['asset-search'].value = '';
  state.searchResults = [];
  renderSearchResults();
  persistWatchlist();
  reconnectFor(added);
  requestRender();
}

function removeFromWatchlist(key) {
  const asset = state.market.registry.get(key);
  state.market.unwatch(key);
  if (state.selectedKey === key) {
    state.selectedKey = state.market.watchOrder[0] ?? null;
  }
  persistWatchlist();
  if (asset?.assetClass === 'crypto') connectCrypto();
  else connectStocks();
  requestRender();
}

function reconnectFor(asset) {
  if (asset.assetClass === 'crypto') connectCrypto();
  else connectStocks();
}

function persistWatchlist() {
  writeJson(
    KEYS.WATCHLIST,
    state.market.watchlist().map((asset) => ({
      provider: asset.provider,
      symbol: asset.symbol,
      assetClass: asset.assetClass,
      base: asset.baseAsset ?? asset.symbol,
      currency: asset.currency,
      name: asset.name,
    })),
  );
}

/* ------------------------------------------------------------------- alerts */

function onRuleSubmit(event) {
  event.preventDefault();
  const form = ui['rule-form'];
  const data = new FormData(form);
  const type = String(data.get('type'));

  const input = {
    assetKey: String(data.get('assetKey') ?? ''),
    type,
    cooldownMs: Number(data.get('cooldownMs')),
    note: String(data.get('note') ?? ''),
  };

  if (type === RULE_TYPE.PRICE) {
    input.direction = String(data.get('direction'));
    input.target = Number(data.get('target'));
  } else if (type === RULE_TYPE.PERCENT) {
    input.thresholdPct = Number(data.get('thresholdPct'));
    input.move = String(data.get('move'));
    input.basis = String(data.get('basis'));
    input.windowMs = Number(data.get('windowMs'));
  } else if (type === RULE_TYPE.VOLUME) {
    input.multiple = Number(data.get('multiple'));
    input.windowMs = Number(data.get('windowMs'));
    input.baselineWindows = 12;
  }

  const errors = validateRule(input);
  showRuleErrors(form, errors);
  if (Object.keys(errors).length > 0) {
    ui['rule-form-status'].textContent = 'יש לתקן את השדות המסומנים.';
    return;
  }

  state.rules = [...state.rules, createRule(input)];
  persistRules();
  const asset = state.market.registry.get(input.assetKey);
  ui['rule-form-status'].textContent = `ההתראה נוספה עבור ${asset?.displaySymbol ?? input.assetKey}.`;
  form.querySelector('[name="note"]').value = '';
  requestRender();
}

function persistRules() {
  writeJson(KEYS.RULES, state.rules);
}

function persistHistory() {
  writeJson(KEYS.HISTORY, state.history.entries.slice(0, 100));
}

/** The engine tick: evaluate, notify, log. */
function alertTick() {
  if (state.rules.length === 0) return;
  const now = Date.now();
  const { rules, events, diagnostics } = runAlertEngine({
    rules: state.rules,
    contextFor: (key) => state.market.contextFor(key),
    now,
  });

  state.rules = rules;
  state.diagnostics = diagnostics;

  if (events.length > 0) {
    for (const event of events) notifier.notify(event);
    state.history.add(events);
    persistRules();
    persistHistory();
    requestRender();
  } else if (Object.keys(diagnostics).length > 0) {
    requestRender();
  }
}

/**
 * The in-page fallback when a desktop notification cannot be shown - the alert
 * still has to be visible to someone looking at the tab.
 * @param {import('./lib/alerts.js').AlertEvent} event
 */
function showToast(event) {
  const toast = el('div', { class: 'toast' });
  toast.append(el('div', { class: 'toast-title', text: event.title }));
  toast.append(el('div', { class: 'toast-body', text: event.body }));
  ui['toast-stack'].append(toast);
  setTimeout(() => toast.remove(), 12_000);
}

function updateNotificationState() {
  const node = ui['notification-state'];
  const permission = notifier.permission;

  if (permission === PERMISSION.GRANTED) {
    node.textContent =
      'התראות הדפדפן פעילות. התראה תופיע גם כשהלשונית ברקע, עם שם הנכס המלא והסמל.';
    node.classList.remove('is-blocked');
    ui['enable-notifications'].disabled = true;
    ui['enable-notifications'].textContent = 'התראות מופעלות';
  } else if (permission === PERMISSION.DENIED) {
    node.textContent =
      'הדפדפן חוסם התראות עבור האתר הזה. ההתראות עדיין ייכתבו בהיסטוריה ויוצגו בתוך הדף, אך לא יופיעו מחוץ לדפדפן. כדי לאפשר: יש ללחוץ על סמל המנעול בשורת הכתובת ולאשר «התראות».';
    node.classList.add('is-blocked');
    ui['enable-notifications'].disabled = true;
    ui['enable-notifications'].textContent = 'התראות חסומות';
  } else if (permission === PERMISSION.UNSUPPORTED) {
    node.textContent = 'הדפדפן אינו תומך בהתראות. ההתראות יוצגו בתוך הדף ובהיסטוריה בלבד.';
    node.classList.add('is-blocked');
    ui['enable-notifications'].disabled = true;
  } else {
    node.textContent =
      'כדי לקבל התראות גם כשהלשונית ברקע, יש ללחוץ «הפעלת התראות בדפדפן» ולאשר את הבקשה.';
    node.classList.remove('is-blocked');
    ui['enable-notifications'].disabled = false;
  }
}

/* ------------------------------------------------------------------- render */

function render() {
  const now = Date.now();

  // Connection pills, including the staleness check.
  const crypto = state.sources.crypto;
  const stock = state.sources.stock;
  crypto.silenceMs = connections.cryptoSocket?.silenceMs() ?? null;
  crypto.stale = connections.cryptoSocket?.isStale() ?? false;
  stock.silenceMs = null;
  stock.stale = connections.stockSocket?.isStale() ?? false;
  renderConnectionPills(ui['connection-pills'], [crypto, stock]);

  // Ticker: live movers when the poll has produced them, the watchlist until then.
  const tickerRows =
    state.movers.length > 0
      ? state.movers
      : state.market
          .watchlist()
          .map((asset) => ({ asset, quote: state.market.quote(asset.key) }))
          .filter((row) => row.quote);
  renderTicker(ui.ticker, topMovers(tickerRows, { limit: 14 }), { onSelect: selectAsset });

  // Watchlist cards.
  const rows = state.market.watchlist().map((asset) => ({
    asset,
    quote: state.market.quote(asset.key),
    age: state.market.ageOf(asset.key, now),
  }));
  renderWatchCards(ui['watch-cards'], rows, {
    selectedKey: state.selectedKey,
    onSelect: selectAsset,
    onRemove: removeFromWatchlist,
  });

  renderDetail(now);

  fillAssetOptions(ui['rule-asset'], state.market.watchlist(), ui['rule-asset'].value || state.selectedKey);
  renderRules(ui['rule-list'], state.rules, {
    assetFor: (key) => state.market.registry.get(key),
    diagnostics: state.diagnostics,
    onToggle: (id, enabled) => {
      state.rules = state.rules.map((rule) =>
        // Re-arm on enable, so a rule switched back on does not fire instantly
        // on a condition that was already true while it was off.
        rule.id === id ? { ...rule, enabled, armed: true } : rule,
      );
      persistRules();
      requestRender();
    },
    onDelete: (id) => {
      state.rules = state.rules.filter((rule) => rule.id !== id);
      persistRules();
      requestRender();
    },
  });

  renderHistory(ui['history-list'], state.history.entries);
}

function renderDetail(now) {
  const key = state.selectedKey;
  const asset = key ? state.market.registry.get(key) : null;

  if (!asset) {
    ui['detail-name'].textContent = '—';
    ui['detail-symbol'].textContent = '';
    ui['detail-source'].textContent = '';
    clear(ui['intraday-stats']);
    clear(ui['price-chart']);
    clear(ui['volume-chart']);
    show(ui['chart-empty'], true);
    return;
  }

  ui['detail-name'].textContent = asset.name ?? asset.displaySymbol;
  ui['detail-symbol'].textContent = asset.name ? asset.displaySymbol : '';

  const quote = state.market.quote(key);
  const series = state.market.series.peek(key);
  const stats = intradayStats(quote, series);

  const age = state.market.ageOf(key, now);
  ui['detail-source'].textContent = [
    `מקור: ${sourceLabel(asset.provider)}`,
    stats.delayed ? 'ייתכן עיכוב' : 'זמן אמת',
    age === null ? 'ממתין לנתונים' : `עודכן ${formatAge(age)} (${formatClock(stats.ts)})`,
  ].join(' · ');

  renderIntradayStats(ui['intraday-stats'], stats, asset);

  const candles = series?.candles ?? [];
  show(ui['chart-empty'], candles.length === 0);

  const label = asset.name ? `${asset.name} / ${asset.displaySymbol}` : asset.displaySymbol;
  const compact = isCompact();
  if (candles.length > 0) {
    renderPriceChart(ui['price-chart'], candles, {
      label,
      tooltip: ui['price-tooltip'],
      readout: ui['chart-readout'],
      compact,
      referencePrice: stats.prevClose ?? stats.open ?? null,
    });
    renderVolumeChart(ui['volume-chart'], candles, {
      label,
      tooltip: ui['volume-tooltip'],
      readout: ui['chart-readout'],
      compact,
    });
  } else {
    clear(ui['price-chart']);
    clear(ui['volume-chart']);
  }
}

function sourceLabel(provider) {
  return { binance: 'Binance', finnhub: 'Finnhub', yahoo: 'Yahoo Finance', coingecko: 'CoinGecko' }[
    provider
  ] ?? provider;
}

function selectAsset(key) {
  state.selectedKey = key;
  const settings = { ...state.settings, selectedKey: key };
  state.settings = settings;
  saveSettings(settings);
  requestRender();
}

/* ------------------------------------------------------------------- wiring */

function wireEvents() {
  ui['asset-search'].addEventListener('input', onSearchInput);
  ui['asset-search'].addEventListener('keydown', onSearchKeydown);
  ui['asset-search'].addEventListener('focus', onSearchInput);
  document.addEventListener('click', (event) => {
    if (!ui['asset-results'].contains(event.target) && event.target !== ui['asset-search']) {
      show(ui['asset-results'], false);
      ui['asset-search'].setAttribute('aria-expanded', 'false');
    }
  });

  ui['class-filter'].addEventListener('change', (event) => {
    state.classFilter = event.target.value;
    onSearchInput();
  });

  ui['rule-form'].addEventListener('submit', onRuleSubmit);
  ui['rule-type'].addEventListener('change', syncRuleFields);

  ui['enable-notifications'].addEventListener('click', async () => {
    await notifier.requestPermission();
    state.settings = { ...state.settings, notificationsRequested: true };
    saveSettings(state.settings);
    updateNotificationState();
  });

  ui['toggle-sound'].addEventListener('click', () => {
    const enabled = !notifier.soundEnabled;
    notifier.soundEnabled = enabled;
    if (enabled) notifier.unlockAudio();
    state.settings = { ...state.settings, soundEnabled: enabled };
    saveSettings(state.settings);
    ui['toggle-sound'].textContent = enabled ? '🔔 צליל פעיל' : '🔕 צליל כבוי';
    ui['toggle-sound'].setAttribute('aria-pressed', enabled ? 'true' : 'false');
  });

  ui['toggle-settings'].addEventListener('click', () => {
    const hidden = ui['settings-panel'].hidden;
    show(ui['settings-panel'], hidden);
    ui['toggle-settings'].setAttribute('aria-expanded', hidden ? 'true' : 'false');
  });

  ui['save-token'].addEventListener('click', () => {
    const token = ui['finnhub-token'].value.trim();
    state.settings = { ...state.settings, finnhubToken: token || null };
    saveSettings(state.settings);
    ui['settings-status'].textContent = token
      ? 'המפתח נשמר בדפדפן. מתחבר מחדש למניות דרך Finnhub…'
      : 'המפתח נמחק. מתחבר מחדש למניות דרך Yahoo.';
    connectStocks();
  });

  ui['clear-token'].addEventListener('click', () => {
    ui['finnhub-token'].value = '';
    state.settings = { ...state.settings, finnhubToken: null };
    saveSettings(state.settings);
    ui['settings-status'].textContent = 'המפתח נמחק מהדפדפן. מתחבר מחדש דרך Yahoo.';
    connectStocks();
  });

  ui['clear-storage'].addEventListener('click', () => {
    clearAll();
    state.rules = [];
    state.history.clear();
    ui['settings-status'].textContent =
      'כל הנתונים השמורים נמחקו מהדפדפן: כללי התראות, היסטוריה, מפתח והגדרות.';
    requestRender();
  });

  ui['export-history'].addEventListener('click', () => {
    if (state.history.entries.length === 0) return;
    const fileName = safeFileName('alerts', todayIso(), 'csv');
    downloadText(fileName, buildHistoryCsv(state.history.entries), 'text/csv');
  });

  ui['clear-history'].addEventListener('click', () => {
    state.history.clear();
    persistHistory();
    requestRender();
  });

  globalThis.matchMedia?.('(max-width: 720px)')?.addEventListener('change', requestRender);

  // A tab restored from the background may have missed reconnect timers.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') requestRender();
  });
}

/** Shows only the fields that belong to the selected rule type. */
function syncRuleFields() {
  const type = ui['rule-type'].value;
  for (const node of ui['rule-form'].querySelectorAll('[data-fields]')) {
    const applies = node.getAttribute('data-fields').split(/\s+/).includes(type);
    node.hidden = !applies;
  }
  // A "since the day's open" percent rule has no time window to choose.
  const basis = ui['rule-form'].querySelector('[name="basis"]');
  const windowControl = ui['rule-window'].closest('.control');
  if (type === 'percent' && basis?.value === 'dayOpen') windowControl.hidden = true;
}

/* --------------------------------------------------------------------- init */

function restoreState() {
  state.settings = loadSettings();
  const { config, rejected } = configFromSearch(globalThis.location?.search ?? '');
  state.config = config;
  if (rejected.length > 0) {
    console.warn('DataScope: נדחו כתובות ספק שאינן ברשימת ההיתר:', rejected);
  }

  const storedRules = readJson(KEYS.RULES, []);
  if (Array.isArray(storedRules)) {
    state.rules = storedRules
      .filter((rule) => rule && rule.assetKey && rule.type)
      // Re-armed on load: the condition may have changed while the tab was
      // closed, and a rule that fires the instant the page opens is noise.
      .map((rule) => createRule({ ...rule, armed: true }));
  }

  const storedHistory = readJson(KEYS.HISTORY, []);
  if (Array.isArray(storedHistory)) state.history = AlertHistory.from(storedHistory, 200);

  const storedWatch = readJson(KEYS.WATCHLIST, null);
  const entries = Array.isArray(storedWatch) && storedWatch.length > 0 ? storedWatch : DEFAULT_WATCHLIST;
  for (const entry of entries) {
    const asset = buildAsset(entry);
    state.market.watch(entry.name ? { ...asset, name: entry.name } : asset);
  }

  state.selectedKey =
    state.settings.selectedKey && state.market.registry.has(state.settings.selectedKey)
      ? state.settings.selectedKey
      : (state.market.watchOrder[0] ?? null);

  if (state.settings.finnhubToken) ui['finnhub-token'].value = state.settings.finnhubToken;
  ui['toggle-sound'].textContent = state.settings.soundEnabled ? '🔔 צליל פעיל' : '🔕 צליל כבוי';
  ui['toggle-sound'].setAttribute('aria-pressed', state.settings.soundEnabled ? 'true' : 'false');
}

function init() {
  cacheElements();
  restoreState();

  notifier = new Notifier({
    soundEnabled: state.settings.soundEnabled,
    onFallback: showToast,
  });

  wireEvents();
  syncRuleFields();
  updateNotificationState();

  connectCrypto();
  connectStocks();
  startMoversPoll();
  loadUniverse();

  setInterval(alertTick, ALERT_TICK_MS);
  // Keeps the "updated N ago" labels and the staleness pills honest while the
  // feed is quiet.
  setInterval(requestRender, 5_000);

  requestRender();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

export { state, init };
