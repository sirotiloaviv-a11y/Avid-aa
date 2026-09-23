import { createProvider } from './data/provider.js';
import { mergeAlerts, filterAlerts } from './data/filters.js';
import { createStore } from './store.js';
import { esc } from './dom.js';
import * as home from './views/home.js';
import * as assets from './views/assets.js';
import * as asset from './views/asset.js';
import * as news from './views/news.js';
import * as events from './views/events.js';
import * as alerts from './views/alerts.js';
import * as settings from './views/settings.js';

const NAV = [
  { path: '', label: 'דף הבית', view: home },
  { path: 'assets', label: 'נכסים', view: assets },
  { path: 'news', label: 'חדשות', view: news },
  { path: 'events', label: 'אירועים', view: events },
  { path: 'alerts', label: 'התראות', view: alerts },
  { path: 'settings', label: 'הגדרות', view: settings },
];

const store = createStore();
const provider = createProvider({ shouldFail: () => store.get().prefs.simulateError });

// Generated alerts are fixed for the session; manual demo alerts live in the store.
let generatedAlerts = null;
async function getAllAlerts() {
  if (!generatedAlerts) generatedAlerts = await provider.getAlerts();
  return mergeAlerts(generatedAlerts, store.get().manualAlerts);
}

function visibleAlerts(all) {
  return filterAlerts(all, { types: store.enabledAlertTypes() });
}

export function parseHash(hash) {
  const raw = (hash || '').replace(/^#\/?/, '');
  const [pathPart, queryPart = ''] = raw.split('?');
  const segments = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
  return { segments, query: Object.fromEntries(new URLSearchParams(queryPart)) };
}

function resolve(segments) {
  const [first = '', second] = segments;
  if (first === 'asset' && second) return { view: asset, nav: 'assets', params: { symbol: second.toUpperCase() } };
  const item = NAV.find((n) => n.path === first);
  if (!item) return null;
  return { view: item.view, nav: item.path, params: {} };
}

const shell = document.getElementById('app');
shell.innerHTML = `
  <div class="demo-banner" role="note">
    <strong>נתוני הדגמה — לא מידע בזמן אמת</strong>
    <span>כל הנכסים, המחירים, הידיעות והאירועים בדיוניים. המערכת אינה מספקת ייעוץ או המלצות, ואינה מחוברת לחשבון מסחר.</span>
  </div>
  <div class="layout">
    <nav class="sidebar" aria-label="ניווט ראשי">
      <div class="brand">מרכז מידע שוק <span class="tag tag-demo">אבטיפוס</span></div>
      <ul>${NAV.map((n) => `<li><a href="#/${n.path}" data-nav="${n.path}">${esc(n.label)}
        ${n.path === 'alerts' ? '<span class="badge" data-unread hidden></span>' : ''}</a></li>`).join('')}</ul>
    </nav>
    <main id="view" tabindex="-1"></main>
  </div>`;

const outlet = document.getElementById('view');
let renderToken = 0;

async function updateUnreadBadge() {
  const badge = shell.querySelector('[data-unread]');
  try {
    const list = visibleAlerts(await getAllAlerts());
    const unread = list.filter((a) => !store.get().readAlerts[a.id]).length;
    badge.hidden = unread === 0;
    badge.textContent = String(unread);
    badge.setAttribute('aria-label', `${unread} התראות שלא נקראו`);
  } catch {
    badge.hidden = true;
  }
}

async function route() {
  const token = ++renderToken;
  const { segments, query } = parseHash(location.hash);
  const match = resolve(segments);
  shell.querySelectorAll('[data-nav]').forEach((a) => {
    const active = match && a.dataset.nav === match.nav;
    a.classList.toggle('active', Boolean(active));
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  if (!match) {
    outlet.innerHTML = `<h1>העמוד לא נמצא</h1><div class="state state-empty"><strong>הכתובת אינה קיימת במערכת.</strong>
      <a class="btn" href="#/">חזרה לדף הבית</a></div>`;
    return;
  }
  const ctx = {
    provider,
    store,
    params: match.params,
    query,
    tz: () => store.get().prefs.timeZone,
    isActive: () => token === renderToken,
    getAllAlerts,
    visibleAlerts,
    refreshBadge: updateUnreadBadge,
    setQuery(next) {
      const params = new URLSearchParams(Object.entries(next).filter(([, v]) => v));
      const base = location.hash.split('?')[0] || '#/';
      const qsText = params.toString();
      history.replaceState(null, '', qsText ? `${base}?${qsText}` : base);
    },
  };
  outlet.innerHTML = '';
  window.scrollTo(0, 0);
  await match.view.render(outlet, ctx);
  if (token === renderToken) outlet.focus({ preventScroll: true });
}

store.subscribe(() => updateUnreadBadge());
window.addEventListener('hashchange', route);
route();
updateUnreadBadge();
