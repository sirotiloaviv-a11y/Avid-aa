import { esc, ltr, qs } from '../dom.js';
import { loadInto, assetRow, emptyView } from '../ui/components.js';
import { searchAssets } from '../data/filters.js';

const TABS = [
  { id: 'all', label: 'הכל' },
  { id: 'stock', label: 'מניות' },
  { id: 'crypto', label: 'קריפטו' },
];

export async function render(root, ctx) {
  let type = TABS.some((t) => t.id === ctx.query.type) ? ctx.query.type : 'all';
  let query = ctx.query.q ?? '';
  const market = ctx.mode === 'market';
  const tz = ctx.tz();
  const subtitle = market
    ? 'הרשימה נקבעת בקובץ ההגדרות המקומי. מחירי מניות: סוף יום. מחירי קריפטו: מושהים בכמה דקות.'
    : 'כל הנכסים בדיוניים. המחירים הם מחירי הדגמה.';

  root.innerHTML = `
    <div class="page-head"><h1>רשימת נכסים</h1>
      <span class="muted small">${esc(subtitle)}</span></div>
    <div class="toolbar">
      <div class="seg" role="tablist" aria-label="סוג נכס">${TABS.map((t) => `<button type="button" role="tab"
        data-tab="${t.id}">${esc(t.label)}</button>`).join('')}</div>
      <label class="search"><span class="sr-only">חיפוש לפי שם או סימול</span>
        <input type="search" id="asset-search" placeholder="חיפוש לפי שם או סימול" autocomplete="off" value="${esc(query)}"></label>
    </div>
    <div id="asset-results"></div>`;

  const results = qs(root, '#asset-results');
  let all = [];

  const draw = () => {
    root.querySelectorAll('[data-tab]').forEach((b) => {
      b.classList.toggle('on', b.dataset.tab === type);
      b.setAttribute('aria-selected', String(b.dataset.tab === type));
    });
    ctx.setQuery({ type: type === 'all' ? '' : type, q: query });
    const list = searchAssets(all, { query, type });
    if (!list.length) {
      const candidate = query.trim().toUpperCase();
      const lookup = market && type !== 'crypto' && /^[A-Z][A-Z0-9.\-]{0,9}$/.test(candidate)
        ? `<a class="btn btn-outline" href="#/asset/${esc(candidate)}" data-lookup>חיפוש המניה ${ltr(candidate)} אצל ספק הנתונים</a>
           <span class="muted small">הפעולה צורכת בקשה אחת ממכסת הספק. קריפטו זמין רק לנכסים שהוגדרו בקובץ ההגדרות.</span>` : '';
      results.innerHTML = emptyView('לא נמצאו נכסים', `${query ? `אין התאמה לחיפוש „${esc(query)}” ברשימה.` : ''} ${lookup}`);
      return;
    }
    const groups = type === 'all' ? ['stock', 'crypto'] : [type];
    results.innerHTML = groups.map((g) => {
      const items = list.filter((a) => a.type === g);
      if (!items.length) return '';
      return `<section class="panel"><h2>${g === 'stock' ? 'מניות' : 'קריפטו'} <span class="muted small">(${items.length})</span></h2>
        <ul class="asset-list">${items.map((a) => assetRow(a, { watched: ctx.store.isWatched(a.symbol), tz })).join('')}</ul></section>`;
    }).join('');
    results.querySelectorAll('[data-watch]').forEach((b) => b.addEventListener('click', () => {
      ctx.store.toggleWatch(b.dataset.watch);
      draw();
    }));
  };

  root.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
    type = b.dataset.tab;
    if (all.length) draw();
  }));
  qs(root, '#asset-search').addEventListener('input', (e) => {
    query = e.target.value;
    if (all.length) draw();
  });

  loadInto(results, ctx, () => ctx.provider.getAssets(), (data) => {
    all = data;
    draw();
  });
}
