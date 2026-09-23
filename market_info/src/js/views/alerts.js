import { esc, qs } from '../dom.js';
import { loadInto, alertCard, emptyView, ALERT_TYPE_LABELS } from '../ui/components.js';
import { filterAlerts } from '../data/filters.js';
import { ALERT_TYPES } from '../data/demoData.js';

export async function render(root, ctx) {
  const tz = ctx.tz();
  let type = ALERT_TYPES.includes(ctx.query.type) ? ctx.query.type : '';
  let symbol = ctx.query.symbol ?? '';
  let status = ['unread', 'read'].includes(ctx.query.status) ? ctx.query.status : 'all';

  root.innerHTML = `
    <div class="page-head"><h1>מרכז התראות מידע</h1>
      <span class="muted small">התראות עובדתיות על נתוני ההדגמה בלבד. הן אינן המלצה לפעולה, ואין שליחה של הודעות מחוץ למערכת.</span></div>
    <div id="alerts-body"></div>`;
  const body = qs(root, '#alerts-body');

  loadInto(body, ctx, () => Promise.all([ctx.getAllAlerts(), ctx.provider.getAssets()]), ([initial, assets]) => {
    let all = initial;
    const bySymbol = Object.fromEntries(assets.map((a) => [a.symbol, a]));
    const enabled = ctx.store.enabledAlertTypes();
    if (type && !enabled.includes(type)) type = '';

    body.innerHTML = `
      <div class="toolbar">
        <label>סוג <select id="a-type"><option value="">כל הסוגים המועדפים</option>
          ${ALERT_TYPES.filter((t) => enabled.includes(t)).map((t) => `<option value="${t}">${esc(ALERT_TYPE_LABELS[t])}</option>`).join('')}</select></label>
        <label>נכס <select id="a-symbol"><option value="">כל הנכסים</option>
          ${assets.map((a) => `<option value="${esc(a.symbol)}">${esc(a.name)} (${esc(a.symbol)})</option>`).join('')}</select></label>
        <label>מצב <select id="a-status"><option value="all">הכל</option><option value="unread">לא נקראו</option>
          <option value="read">נקראו</option></select></label>
      </div>
      <div class="toolbar">
        <button type="button" class="btn" id="demo-trigger" ${enabled.length ? '' : 'disabled'}>הפעל אירוע הדגמה</button>
        <button type="button" class="btn btn-outline" id="mark-all">סמן את המוצגות כנקראו</button>
        <span class="muted small" id="a-count" aria-live="polite"></span>
      </div>
      <p class="muted small" id="hidden-note"></p>
      <div id="alert-list" class="stack"></div>`;

    const typeSel = qs(body, '#a-type');
    const symbolSel = qs(body, '#a-symbol');
    const statusSel = qs(body, '#a-status');
    typeSel.value = type;
    symbolSel.value = bySymbol[symbol] ? symbol : '';
    symbol = symbolSel.value;
    statusSel.value = status;

    const current = () => filterAlerts(all, {
      types: type ? [type] : enabled, symbol, status, readIds: ctx.store.get().readAlerts,
    });

    const draw = () => {
      ctx.setQuery({ type, symbol, status: status === 'all' ? '' : status });
      const list = current();
      const read = ctx.store.get().readAlerts;
      const unread = filterAlerts(all, { types: enabled, status: 'unread', readIds: read }).length;
      qs(body, '#a-count').textContent = `${list.length} מוצגות · ${unread} לא נקראו`;
      const hidden = all.length - filterAlerts(all, { types: enabled }).length;
      qs(body, '#hidden-note').textContent = !enabled.length
        ? 'כל סוגי ההתראות כבויים בהגדרות.'
        : hidden ? `${hidden} התראות מסוגים שכובו בהגדרות אינן מוצגות.` : '';
      const listEl = qs(body, '#alert-list');
      listEl.innerHTML = list.length
        ? list.map((a) => alertCard(a, bySymbol[a.symbol], tz, { read: Boolean(read[a.id]) })).join('')
        : emptyView('אין התראות להצגה', 'שנו את הסינון או לחצו „הפעל אירוע הדגמה”.');
      listEl.querySelectorAll('[data-toggle-read]').forEach((b) => b.addEventListener('click', () => {
        const id = b.dataset.toggleRead;
        if (ctx.store.get().readAlerts[id]) ctx.store.markUnread(id); else ctx.store.markRead([id]);
        draw();
      }));
    };

    typeSel.addEventListener('change', () => { type = typeSel.value; draw(); });
    symbolSel.addEventListener('change', () => { symbol = symbolSel.value; draw(); });
    statusSel.addEventListener('change', () => { status = statusSel.value; draw(); });
    qs(body, '#mark-all').addEventListener('click', () => {
      ctx.store.markRead(current().map((a) => a.id));
      draw();
    });

    const trigger = qs(body, '#demo-trigger');
    trigger.addEventListener('click', async () => {
      trigger.disabled = true;
      trigger.textContent = 'יוצר אירוע הדגמה…';
      try {
        const alert = await ctx.provider.createDemoAlert(ctx.store.enabledAlertTypes());
        if (alert) ctx.store.addManualAlert(alert);
        all = await ctx.getAllAlerts();
        if (!ctx.isActive()) return;
        draw();
        const card = body.querySelector(`[data-alert-id="${CSS.escape(alert?.id ?? '')}"]`);
        card?.classList.add('flash');
      } catch (err) {
        if (!ctx.isActive()) return;
        qs(body, '#hidden-note').textContent = `לא ניתן היה ליצור אירוע הדגמה: ${err.message}`;
      } finally {
        trigger.disabled = false;
        trigger.textContent = 'הפעל אירוע הדגמה';
      }
    });
    draw();
  });
}
