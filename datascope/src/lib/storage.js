/**
 * Local persistence for alert rules, history and settings.
 *
 * An alert you set at 09:00 has to survive a refresh at 11:00, so unlike the
 * previous version of this app there is deliberate persistence here. It is all
 * per-browser: nothing is uploaded, and the storage APIs are wrapped because
 * they are not as reliable as they look - private windows, blocked site data and
 * quota exhaustion all throw, and none of that should take the dashboard down.
 *
 * The Finnhub API key lives here too. It is the user's own key, it is sent only
 * to finnhub.io, and the README says plainly that it is stored in the browser so
 * nobody is surprised by it later.
 */

const PREFIX = 'datascope:';
const SCHEMA_VERSION = 2;

/**
 * @param {string} key
 * @param {unknown} fallback
 */
export function readJson(key, fallback = null) {
  try {
    const raw = globalThis.localStorage?.getItem(PREFIX + key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return fallback;
    if (parsed.v !== SCHEMA_VERSION) return fallback;
    return parsed.d;
  } catch {
    // Unavailable or corrupt storage is not an error worth surfacing: the app
    // simply starts empty.
    return fallback;
  }
}

/**
 * @param {string} key
 * @param {unknown} value
 * @returns {boolean} False when the write did not happen.
 */
export function writeJson(key, value) {
  try {
    globalThis.localStorage?.setItem(PREFIX + key, JSON.stringify({ v: SCHEMA_VERSION, d: value }));
    return true;
  } catch {
    return false;
  }
}

/** @param {string} key */
export function remove(key) {
  try {
    globalThis.localStorage?.removeItem(PREFIX + key);
  } catch {
    /* nothing to do */
  }
}

/** Clears everything this app stored, and nothing else. */
export function clearAll() {
  try {
    const storage = globalThis.localStorage;
    if (!storage) return;
    const keys = [];
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (key && key.startsWith(PREFIX)) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
  } catch {
    /* nothing to do */
  }
}

export function isAvailable() {
  try {
    const probe = `${PREFIX}__probe__`;
    globalThis.localStorage?.setItem(probe, '1');
    globalThis.localStorage?.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

export const KEYS = Object.freeze({
  RULES: 'rules',
  HISTORY: 'history',
  SETTINGS: 'settings',
  WATCHLIST: 'watchlist',
});

/**
 * Settings, with every field defaulted so a partially written record from an
 * older build cannot leave a field undefined.
 * @typedef {object} Settings
 * @property {string|null} finnhubToken
 * @property {boolean} soundEnabled
 * @property {boolean} notificationsRequested
 * @property {string|null} selectedKey
 * @property {'candles'|'line'} chartMode
 */

/** @returns {Settings} */
export function loadSettings() {
  const stored = readJson(KEYS.SETTINGS, {}) ?? {};
  return {
    finnhubToken: typeof stored.finnhubToken === 'string' && stored.finnhubToken ? stored.finnhubToken : null,
    soundEnabled: stored.soundEnabled !== false,
    notificationsRequested: stored.notificationsRequested === true,
    selectedKey: typeof stored.selectedKey === 'string' ? stored.selectedKey : null,
    chartMode: stored.chartMode === 'line' ? 'line' : 'candles',
  };
}

/** @param {Settings} settings */
export function saveSettings(settings) {
  return writeJson(KEYS.SETTINGS, settings);
}
