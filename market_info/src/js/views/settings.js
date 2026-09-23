import { esc, ltr, qs } from '../dom.js';
import { TIME_ZONES, tzOffset, formatDateTime } from '../format.js';
import { ALERT_TYPE_LABELS, emptyView, loadInto } from '../ui/components.js';
import { ALERT_TYPES, PRICE_ALERT_THRESHOLD_PCT, VOLUME_ALERT_MULTIPLE } from '../data/demoData.js';
import { MarketProvider } from '../data/marketProvider.js';

const TYPE_HINTS = {
  price: `שינוי של ${PRICE_ALERT_THRESHOLD_PCT}% ומעלה במחיר הסגירה היומי.`,
  volume: `נפח יומי של פי ${VOLUME_ALERT_MULTIPLE} ומעלה מהממוצע ל-20 ימים.`,
  news: 'פרסום ידיעת הדגמה חדשה על נכס.',
};

const MODES = [
  { id: 'demo', label: 'הדגמה', hint: 'נכסים, מחירים, חדשות ואירועים בדיוניים. עובד בלי שום הגדרה.' },
  { id: 'market', label: 'נתוני שוק', hint: 'מחירים והיסטוריה ממקורות אמיתיים (מושהים / סוף יום). דורש מפתחות בקובץ ההגדרות המקומי. חדשות, אירועים והתראות טרם חוברו.' },
];

const SETUP_STEPS = `
  <ol class="steps">
    <li>בתיקייה <code dir="ltr">market_info</code> יש קובץ בשם <code dir="ltr">.env.example</code>. צרו עותק שלו באותה תיקייה וקראו לעותק <code dir="ltr">.env</code>.</li>
    <li>הירשמו בעצמכם לקבלת מפתח חינמי אצל כל ספק (המערכת לא פותחת חשבונות ולא רוכשת שירות):
      <ul>
        <li>מניות — Alpha Vantage: <span dir="ltr">https://www.alphavantage.co/support/#api-key</span></li>
        <li>קריפטו — CoinGecko, מסלול Demo: דרך חשבון מפתחים באתר <span dir="ltr">coingecko.com</span></li>
      </ul></li>
    <li>פתחו את <code dir="ltr">.env</code> בעורך טקסט (למשל Notepad) והדביקו כל מפתח מיד אחרי סימן השוויון, במקום הטקסט <code dir="ltr">your-key</code>:
      <code dir="ltr" class="block">ALPHA_VANTAGE_API_KEY=your-key</code>
      <code dir="ltr" class="block">COINGECKO_DEMO_API_KEY=your-key</code></li>
    <li>שמרו את הקובץ, סגרו את חלון השרת והפעילו אותו מחדש.</li>
    <li>חזרו לכאן ובחרו „נתוני שוק”.</li>
  </ol>
  <p class="muted small">אין להדביק מפתחות בצ׳אט, באתר או בקוד. הקובץ <code dir="ltr">.env</code> נשאר במחשב שלכם בלבד: הוא אינו נשמר ב-Git ואינו נשלח לדפדפן.</p>`;

function usageLine(p) {
  const u = p.usage;
  const parts = [];
  if (Number.isFinite(u.limits.perDay)) parts.push(`היום: ${u.dayCount} מתוך ${u.limits.perDay}`);
  if (Number.isFinite(u.limits.perMonth)) parts.push(`החודש: ${u.monthCount} מתוך ${u.limits.perMonth}`);
  if (Number.isFinite(u.limits.perMinute)) parts.push(`עד ${u.limits.perMinute} בדקה`);
  return parts.join(' · ');
}

function providerStatus(status, tz) {
  const row = (label, p) => `<div class="provider ${p.configured ? 'ok' : 'setup'}" data-provider="${esc(p.id)}">
      <h3>${esc(label)}: ${esc(p.name)} ${p.configured
        ? '<span class="tag">מפתח הוגדר</span>'
        : '<span class="tag tag-setup">נדרשת הגדרה</span>'}</h3>
      <p class="small">סוג הנתונים: ${esc(p.delayLabel)}</p>
      <p class="small muted">בקשות שנשלחו (לפי מונה מקומי): ${esc(usageLine(p))}</p>
      ${p.usage.blockedUntil && p.usage.blockedUntil > status.serverTime
        ? `<p class="small warn-text">הספק הגביל בקשות עד ${esc(formatDateTime(p.usage.blockedUntil, tz))}</p>` : ''}
      ${p.configured ? '' : `<p class="small">חסר המשתנה <code dir="ltr">${esc(p.keyEnv)}</code> בקובץ <code dir="ltr">.env</code>.</p>`}
      ${p.attribution ? `<p class="small attribution">${esc(p.attribution)}</p>` : ''}
    </div>`;
  const anyMissing = !status.providers.stocks.configured || !status.providers.crypto.configured;
  return `
    ${row('מניות', status.providers.stocks)}
    ${row('קריפטו', status.providers.crypto)}
    <p class="small">נכסים מוגדרים — מניות: ${status.universe.stocks.map((s) => ltr(s)).join(', ') || 'אין'};
      קריפטו: ${status.universe.crypto.map((s) => ltr(s)).join(', ') || 'אין'}</p>
    ${status.warnings.length ? `<p class="small warn-text">${status.warnings.map(esc).join('<br>')}</p>` : ''}
    <details ${anyMissing ? 'open' : ''}><summary><strong>איך מגדירים מפתחות (פעם אחת)</strong></summary>${SETUP_STEPS}</details>`;
}

export async function render(root, ctx) {
  const draw = () => {
    const state = ctx.store.get();
    const { prefs } = state;
    const watchlist = ctx.store.getWatchlist();
    root.innerHTML = `
      <div class="page-head"><h1>הגדרות</h1>
        <span class="muted small">ההעדפות ורשימות המעקב נשמרות בדפדפן זה בלבד (אחסון מקומי). אין חשבון או סנכרון.</span></div>
      ${ctx.store.isPersistent() ? '' : `<div class="state state-error" role="alert">
        הדפדפן חוסם אחסון מקומי. ההגדרות יישמרו רק עד סגירת הלשונית.</div>`}
      <form id="prefs" class="panel form">
        <fieldset><legend>מצב נתונים</legend>
          ${MODES.map((m) => `<label class="check"><input type="radio" name="dataMode" value="${m.id}" ${prefs.dataMode === m.id ? 'checked' : ''}>
            <span><strong>${esc(m.label)}</strong> <span class="muted small">${esc(m.hint)}</span></span></label>`).join('')}
          <p class="muted small">לכל מצב רשימת מעקב נפרדת. נתוני הדגמה לעולם אינם משמשים להשלמת נתוני שוק חסרים.</p>
        </fieldset>
        <fieldset><legend>סוגי התראות מועדפים (מצב הדגמה)</legend>
          ${ALERT_TYPES.map((t) => `<label class="check"><input type="checkbox" name="type" value="${t}" ${prefs.alertTypes[t] ? 'checked' : ''}>
            <span><strong>${esc(ALERT_TYPE_LABELS[t])}</strong> <span class="muted small">${esc(TYPE_HINTS[t])}</span></span></label>`).join('')}
        </fieldset>
        <fieldset><legend>אזור זמן</legend>
          <label>אזור הזמן להצגת שעות <select name="timeZone">
            ${TIME_ZONES.map((z) => `<option value="${esc(z.id)}" ${z.id === prefs.timeZone ? 'selected' : ''}>${esc(z.label)} (${esc(tzOffset(z.id))})</option>`).join('')}
          </select></label>
        </fieldset>
        <fieldset><legend>בדיקת ממשק (מצב הדגמה)</legend>
          <label class="check"><input type="checkbox" name="simulateError" ${prefs.simulateError ? 'checked' : ''}>
            <span><strong>הדמיית שגיאת טעינה</strong> <span class="muted small">כל טעינת נתוני הדגמה תיכשל, כדי לבדוק את מסכי השגיאה.</span></span></label>
        </fieldset>
        <div class="form-actions"><button type="submit" class="btn">שמירת העדפות</button>
          <span id="saved" class="muted" role="status" aria-live="polite"></span></div>
      </form>
      <section class="panel"><h2>מקורות נתוני שוק</h2><div id="sources"></div></section>
      <section class="panel"><h2>רשימת המעקב השמורה (${prefs.dataMode === 'demo' ? 'מצב הדגמה' : 'מצב נתוני שוק'})</h2><div id="saved-watchlist"></div></section>
      <section class="panel"><h2>מה המערכת אינה עושה</h2>
        <p>אין חיבור לחשבון מסחר, אין ביצוע עסקאות, אין המלצות קנייה או מכירה ואין שליחת הודעות.
          גם במצב נתוני שוק הנתונים אינם בזמן אמת.</p></section>
      <section class="panel"><h2>איפוס</h2>
        <p class="muted small">מחיקת ההעדפות, רשימות המעקב, התזכורות וסימוני הקריאה מהדפדפן. המפתחות בקובץ ההגדרות המקומי אינם מושפעים.</p>
        <button type="button" class="btn btn-danger" id="reset">איפוס כל הנתונים המקומיים</button></section>`;

    const sources = qs(root, '#sources');
    const status = ctx.provider instanceof MarketProvider ? ctx.provider : new MarketProvider();
    loadInto(sources, ctx, () => status.getStatus(), (s) => { sources.innerHTML = providerStatus(s, ctx.tz()); }, 'בודק את מצב המקורות…');

    const wl = qs(root, '#saved-watchlist');
    wl.innerHTML = watchlist.length
      ? `<ul class="plain-list">${watchlist.map((s) => `<li><a href="#/asset/${esc(s)}">${ltr(s, 'symbol')}</a>
          <button type="button" class="btn btn-sm btn-ghost" data-remove="${esc(s)}">הסרה</button></li>`).join('')}</ul>`
      : emptyView('רשימת המעקב ריקה', '<a href="#/assets">הוספת נכסים</a>');
    wl.querySelectorAll('[data-remove]').forEach((b) => b.addEventListener('click', () => {
      ctx.store.toggleWatch(b.dataset.remove);
      draw();
    }));

    qs(root, '#prefs').addEventListener('submit', (e) => {
      e.preventDefault();
      const form = e.target;
      const checked = new Set([...form.querySelectorAll('input[name="type"]:checked')].map((i) => i.value));
      const modeChanged = form.dataMode.value !== prefs.dataMode;
      ctx.store.setPrefs({
        dataMode: form.dataMode.value,
        alertTypes: Object.fromEntries(ALERT_TYPES.map((t) => [t, checked.has(t)])),
        timeZone: form.timeZone.value,
        simulateError: form.simulateError.checked,
      });
      const msg = ctx.store.isPersistent()
        ? 'ההעדפות נשמרו במכשיר זה.' : 'ההעדפות הוחלו, אך לא ניתן לשמור אותן בדפדפן זה.';
      // A mode change swaps the data source, so the screen is rebuilt by the router.
      if (modeChanged) {
        window.dispatchEvent(new HashChangeEvent('hashchange'));
        queueMicrotask(() => { const el = document.getElementById('saved'); if (el) el.textContent = msg; });
        return;
      }
      draw();
      qs(root, '#saved').textContent = msg;
    });

    qs(root, '#reset').addEventListener('click', () => {
      if (!window.confirm('למחוק את כל ההעדפות והנתונים המקומיים?')) return;
      ctx.store.reset();
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
  };
  draw();
}
