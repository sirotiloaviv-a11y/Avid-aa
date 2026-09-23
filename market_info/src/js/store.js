// Local state: preferences, watchlist, reminders and alert read-state. It is
// kept in the browser's localStorage only; nothing leaves the device.

export const STORAGE_KEY = 'market-info-demo.v1';

export const DATA_MODES = ['demo', 'market'];

// Watchlists are kept per mode: demo symbols are fictional and must never
// appear as if they were market symbols, and vice versa.
export const DEFAULT_STATE = Object.freeze({
  watchlists: { demo: ['ORLN', 'MGDL', 'NOVX', 'ZFRT'], market: [] },
  selected: { demo: 'ORLN', market: null },
  prefs: {
    dataMode: 'demo',
    alertTypes: { price: true, volume: true, news: true },
    timeZone: 'Asia/Jerusalem',
    simulateError: false,
  },
  reminders: {},
  readAlerts: {},
  manualAlerts: [],
});

function defaults() {
  return structuredClone(DEFAULT_STATE);
}

function merge(saved) {
  const base = defaults();
  if (!saved || typeof saved !== 'object') return base;
  // Stage-1 state stored a single demo watchlist.
  if (Array.isArray(saved.watchlist) && !saved.watchlists) {
    saved = { ...saved, watchlists: { demo: saved.watchlist }, selected: { demo: saved.selectedSymbol ?? null } };
  }
  const { watchlist, selectedSymbol, ...rest } = saved;
  const prefs = { ...base.prefs, ...(saved.prefs ?? {}) };
  if (!DATA_MODES.includes(prefs.dataMode)) prefs.dataMode = 'demo';
  return {
    ...base,
    ...rest,
    watchlists: { ...base.watchlists, ...(saved.watchlists ?? {}) },
    selected: { ...base.selected, ...(saved.selected ?? {}) },
    prefs: {
      ...prefs,
      alertTypes: { ...base.prefs.alertTypes, ...(saved.prefs?.alertTypes ?? {}) },
    },
  };
}

export function createStore(storage = safeLocalStorage()) {
  let state = load();
  const listeners = new Set();
  let persistent = storage !== null;

  function load() {
    if (!storage) return defaults();
    try {
      return merge(JSON.parse(storage.getItem(STORAGE_KEY) ?? 'null'));
    } catch {
      return defaults();
    }
  }

  function save() {
    if (!storage) return;
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(state));
      persistent = true;
    } catch {
      persistent = false;
    }
  }

  function update(mutator) {
    const next = structuredClone(state);
    mutator(next);
    state = next;
    save();
    listeners.forEach((fn) => fn(state));
  }

  return {
    get: () => state,
    isPersistent: () => persistent,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    mode: () => state.prefs.dataMode,
    getWatchlist: () => state.watchlists[state.prefs.dataMode] ?? [],
    getSelected: () => state.selected[state.prefs.dataMode] ?? null,
    isWatched: (symbol) => (state.watchlists[state.prefs.dataMode] ?? []).includes(symbol),
    toggleWatch(symbol) {
      update((s) => {
        const mode = s.prefs.dataMode;
        const list = s.watchlists[mode] ?? [];
        if (list.includes(symbol)) {
          s.watchlists[mode] = list.filter((x) => x !== symbol);
          if (s.selected[mode] === symbol) s.selected[mode] = s.watchlists[mode][0] ?? null;
        } else {
          s.watchlists[mode] = [...list, symbol];
          if (!s.selected[mode]) s.selected[mode] = symbol;
        }
      });
    },
    selectSymbol(symbol) {
      update((s) => { s.selected[s.prefs.dataMode] = symbol; });
    },
    setPrefs(prefs) {
      update((s) => {
        s.prefs = { ...s.prefs, ...prefs, alertTypes: { ...s.prefs.alertTypes, ...(prefs.alertTypes ?? {}) } };
      });
    },
    enabledAlertTypes: () => Object.entries(state.prefs.alertTypes).filter(([, on]) => on).map(([t]) => t),
    hasReminder: (eventId) => Boolean(state.reminders[eventId]),
    toggleReminder(eventId) {
      update((s) => {
        if (s.reminders[eventId]) delete s.reminders[eventId];
        else s.reminders[eventId] = Date.now();
      });
    },
    markRead(ids) {
      update((s) => { ids.forEach((id) => { s.readAlerts[id] = true; }); });
    },
    markUnread(id) {
      update((s) => { delete s.readAlerts[id]; });
    },
    addManualAlert(alert) {
      update((s) => { s.manualAlerts = [alert, ...s.manualAlerts].slice(0, 50); });
    },
    reset() {
      state = defaults();
      save();
      listeners.forEach((fn) => fn(state));
    },
  };
}

function safeLocalStorage() {
  try {
    const s = globalThis.localStorage;
    if (!s) return null;
    const probe = '__probe__';
    s.setItem(probe, probe);
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}
