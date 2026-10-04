/*
 * Shadow AI Shield — service worker.
 *
 * Owns all persistent state in chrome.storage.local:
 *   enabled : boolean
 *   stats   : { day: "YYYY-MM-DD", maskedToday: number, byType: { [type]: number } }
 *   log     : [{ ts, type, site }]   newest first, capped at LOG_LIMIT
 *
 * Only data types are stored — never the masked values.
 */

const LOG_LIMIT = 100;

const DEFAULTS = {
  enabled: true,
  stats: { day: today(), maskedToday: 0, byType: {} },
  log: [],
};

function today() {
  return new Date().toLocaleDateString("en-CA"); // local YYYY-MM-DD
}

async function getState() {
  const state = await chrome.storage.local.get(DEFAULTS);
  if (state.stats.day !== today()) {
    state.stats = { day: today(), maskedToday: 0, byType: {} };
    await chrome.storage.local.set({ stats: state.stats });
  }
  return state;
}

// Serialize writes: two tabs reporting at once must not lose an increment.
let queue = Promise.resolve();
function enqueue(fn) {
  const run = queue.then(fn);
  queue = run.catch(() => {});
  return run;
}

async function recordFindings(findings, site) {
  const state = await getState();
  const ts = Date.now();
  for (const type of findings) {
    state.stats.maskedToday += 1;
    state.stats.byType[type] = (state.stats.byType[type] || 0) + 1;
    state.log.unshift({ ts, type, site });
  }
  state.log.length = Math.min(state.log.length, LOG_LIMIT);
  await chrome.storage.local.set({ stats: state.stats, log: state.log });
  await updateBadge(state);
}

async function updateBadge(state) {
  state = state || (await getState());
  if (!state.enabled) {
    await chrome.action.setBadgeText({ text: "OFF" });
    await chrome.action.setBadgeBackgroundColor({ color: "#6b7280" });
    return;
  }
  const n = state.stats.maskedToday;
  await chrome.action.setBadgeText({ text: n ? String(n > 999 ? "999+" : n) : "" });
  await chrome.action.setBadgeBackgroundColor({ color: "#16a34a" });
}

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get(null);
  const missing = Object.fromEntries(Object.entries(DEFAULTS).filter(([k]) => !(k in existing)));
  if (Object.keys(missing).length) await chrome.storage.local.set(missing);
  await updateBadge();
});

chrome.runtime.onStartup.addListener(() => updateBadge());

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handlers = {
    PII_MASKED: () =>
      enqueue(() => recordFindings(Array.isArray(msg.findings) ? msg.findings.map(String) : [], String(msg.site || ""))),
    GET_STATE: () => getState(),
    SET_ENABLED: () =>
      enqueue(async () => {
        await chrome.storage.local.set({ enabled: Boolean(msg.enabled) });
        await updateBadge();
      }),
    CLEAR_LOG: () =>
      enqueue(async () => {
        await chrome.storage.local.set({ log: [], stats: { day: today(), maskedToday: 0, byType: {} } });
        await updateBadge();
      }),
  };

  const handler = handlers[msg && msg.type];
  if (!handler) return false;
  handler()
    .then((result) => sendResponse({ ok: true, result }))
    .catch((err) => sendResponse({ ok: false, error: String(err) }));
  return true; // keep the channel open for the async response
});
