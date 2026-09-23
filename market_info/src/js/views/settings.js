import { esc, ltr, qs } from '../dom.js';
import { TIME_ZONES, tzOffset } from '../format.js';
import { ALERT_TYPE_LABELS, emptyView } from '../ui/components.js';
import { ALERT_TYPES, PRICE_ALERT_THRESHOLD_PCT, VOLUME_ALERT_MULTIPLE } from '../data/demoData.js';

const TYPE_HINTS = {
  price: `שינוי של ${PRICE_ALERT_THRESHOLD_PCT}% ומעלה במחיר הסגירה היומי.`,
  volume: `נפח יומי של פי ${VOLUME_ALERT_MULTIPLE} ומעלה מהממוצע ל-20 ימים.`,
  news: 'פרסום ידיעת הדגמה חדשה על נכס.',
};

export async function render(root, ctx) {
  const draw = () => {
    const state = ctx.store.get();
    const { prefs } = state;
    root.innerHTML = `
      <div class="page-head"><h1>הגדרות</h1>
        <span class="muted small">ההעדפות ורשימת המעקב נשמרות בדפדפן זה בלבד (אחסון מקומי). אין שרת, חשבון או סנכרון.</span></div>
      ${ctx.store.isPersistent() ? '' : `<div class="state state-error" role="alert">
        הדפדפן חוסם אחסון מקומי. ההגדרות יישמרו רק עד סגירת הלשונית.</div>`}
      <form id="prefs" class="panel form">
        <fieldset><legend>סוגי התראות מועדפים</legend>
          ${ALERT_TYPES.map((t) => `<label class="check"><input type="checkbox" name="type" value="${t}" ${prefs.alertTypes[t] ? 'checked' : ''}>
            <span><strong>${esc(ALERT_TYPE_LABELS[t])}</strong> <span class="muted small">${esc(TYPE_HINTS[t])}</span></span></label>`).join('')}
        </fieldset>
        <fieldset><legend>אזור זמן</legend>
          <label>אזור הזמן להצגת שעות <select name="timeZone">
            ${TIME_ZONES.map((z) => `<option value="${esc(z.id)}" ${z.id === prefs.timeZone ? 'selected' : ''}>${esc(z.label)} (${esc(tzOffset(z.id))})</option>`).join('')}
          </select></label>
        </fieldset>
        <fieldset><legend>בדיקת ממשק</legend>
          <label class="check"><input type="checkbox" name="simulateError" ${prefs.simulateError ? 'checked' : ''}>
            <span><strong>הדמיית שגיאת טעינה</strong> <span class="muted small">כל טעינת נתונים תיכשל, כדי לבדוק את מסכי השגיאה.</span></span></label>
        </fieldset>
        <div class="form-actions"><button type="submit" class="btn">שמירת העדפות</button>
          <span id="saved" class="muted" role="status" aria-live="polite"></span></div>
      </form>
      <section class="panel"><h2>רשימת המעקב השמורה</h2><div id="saved-watchlist"></div></section>
      <section class="panel"><h2>מקור הנתונים</h2>
        <p>המערכת מציגה <strong>נתוני הדגמה מקומיים</strong> בלבד. היא אינה מחוברת למידע שוק חי, לשירות בינה מלאכותית,
          לחשבון מסחר או לשירות הודעות. אין בה המלצות קנייה או מכירה.</p></section>
      <section class="panel"><h2>איפוס</h2>
        <p class="muted small">מחיקת ההעדפות, רשימת המעקב, התזכורות וסימוני הקריאה מהדפדפן.</p>
        <button type="button" class="btn btn-danger" id="reset">איפוס כל הנתונים המקומיים</button></section>`;

    const wl = qs(root, '#saved-watchlist');
    wl.innerHTML = state.watchlist.length
      ? `<ul class="plain-list">${state.watchlist.map((s) => `<li><a href="#/asset/${esc(s)}">${ltr(s, 'symbol')}</a>
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
      ctx.store.setPrefs({
        alertTypes: Object.fromEntries(ALERT_TYPES.map((t) => [t, checked.has(t)])),
        timeZone: form.timeZone.value,
        simulateError: form.simulateError.checked,
      });
      draw();
      qs(root, '#saved').textContent = ctx.store.isPersistent()
        ? 'ההעדפות נשמרו במכשיר זה.' : 'ההעדפות הוחלו, אך לא ניתן לשמור אותן בדפדפן זה.';
    });

    qs(root, '#reset').addEventListener('click', () => {
      if (!window.confirm('למחוק את כל ההעדפות והנתונים המקומיים?')) return;
      ctx.store.reset();
      draw();
      qs(root, '#saved').textContent = 'הנתונים המקומיים אופסו.';
    });
  };
  draw();
}
