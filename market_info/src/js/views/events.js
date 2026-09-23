import { esc, qs } from '../dom.js';
import { loadInto, eventRow, emptyView, notConnectedView } from '../ui/components.js';
import {
  dateKey, addDays, weekKeys, isValidDateKey, formatDayKey, formatWeekdayShort, formatDateTime, tzLabel,
} from '../format.js';

export function groupEventsByDay(events, tz) {
  const map = {};
  for (const e of events) (map[dateKey(e.time, tz)] ??= []).push(e);
  return map;
}

export async function render(root, ctx) {
  if (!ctx.provider.capabilities.events) {
    root.innerHTML = `<div class="page-head"><h1>לוח אירועים</h1></div>${notConnectedView('אירועים')}`;
    return;
  }
  const tz = ctx.tz();
  const todayKey = dateKey(Date.now(), tz);
  let view = ctx.query.view === 'week' ? 'week' : 'day';
  let day = isValidDateKey(ctx.query.date) ? ctx.query.date : todayKey;

  root.innerHTML = `
    <div class="page-head"><h1>לוח אירועים</h1>
      <div class="tz-box" role="note"><strong>אזור זמן מוצג:</strong> ${esc(tzLabel(tz))}
        <a class="link small" href="#/settings">שינוי</a></div></div>
    <div id="events-body"></div>`;
  const body = qs(root, '#events-body');

  loadInto(body, ctx, () => ctx.provider.getEvents(), (events) => {
    const byDay = groupEventsByDay(events, tz);
    body.innerHTML = `
      <div class="toolbar">
        <div class="seg" role="tablist" aria-label="תצוגה">
          <button type="button" role="tab" data-view="day">יומי</button>
          <button type="button" role="tab" data-view="week">שבועי</button></div>
        <div class="pager">
          <button type="button" class="btn btn-sm btn-outline" data-step="-1" aria-label="הקודם">→ הקודם</button>
          <button type="button" class="btn btn-sm btn-ghost" data-today>היום</button>
          <button type="button" class="btn btn-sm btn-outline" data-step="1" aria-label="הבא">הבא ←</button></div>
        <strong id="range-label" aria-live="polite"></strong>
      </div>
      <div id="calendar"></div>
      <section class="panel"><h2>התזכורות שלי</h2>
        <p class="muted small">תזכורות נשמרות בדפדפן זה בלבד ומוצגות בתוך המערכת. לא נשלחות הודעות חיצוניות.</p>
        <div id="my-reminders"></div></section>`;

    const bindReminders = (el) => el.querySelectorAll('[data-reminder]').forEach((b) =>
      b.addEventListener('click', () => {
        ctx.store.toggleReminder(b.dataset.reminder);
        draw();
      }));

    const dayList = (key) => {
      const list = byDay[key] ?? [];
      return list.length
        ? `<ul class="event-list">${list.map((e) => eventRow(e, tz, { reminder: ctx.store.hasReminder(e.id) })).join('')}</ul>`
        : emptyView('אין אירועים ביום זה');
    };

    const draw = () => {
      ctx.setQuery({ view, date: day });
      body.querySelectorAll('[data-view]').forEach((b) => {
        b.classList.toggle('on', b.dataset.view === view);
        b.setAttribute('aria-selected', String(b.dataset.view === view));
      });
      const cal = qs(body, '#calendar');
      if (view === 'day') {
        qs(body, '#range-label').textContent = `${formatDayKey(day)}${day === todayKey ? ' (היום)' : ''}`;
        cal.innerHTML = `<section class="panel">${dayList(day)}</section>`;
      } else {
        const keys = weekKeys(day);
        qs(body, '#range-label').textContent = `שבוע ${formatDayKey(keys[0], { withWeekday: false })} – ${formatDayKey(keys[6], { withWeekday: false })}`;
        cal.innerHTML = `<div class="week">${keys.map((k) => `<section class="week-day ${k === todayKey ? 'today' : ''}">
          <h3><span>${esc(formatWeekdayShort(k))}</span> <span class="muted">${esc(formatDayKey(k, { withWeekday: false }))}</span>
          ${k === todayKey ? '<span class="tag tag-warn">היום</span>' : ''}</h3>
          ${(byDay[k] ?? []).length ? dayList(k) : '<p class="muted small">אין אירועים</p>'}</section>`).join('')}</div>`;
      }
      bindReminders(cal);

      const saved = events.filter((e) => ctx.store.hasReminder(e.id));
      const rem = qs(body, '#my-reminders');
      rem.innerHTML = saved.length
        ? `<ul class="event-list">${saved.map((e) => `<li class="event-day-label">${esc(formatDateTime(e.time, tz))}</li>
            ${eventRow(e, tz, { reminder: true })}`).join('')}</ul>`
        : emptyView('אין תזכורות שמורות', 'לחצו „שמור תזכורת” ליד אירוע כדי לשמור אותו כאן.');
      bindReminders(rem);
    };

    body.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
      view = b.dataset.view; draw();
    }));
    body.querySelectorAll('[data-step]').forEach((b) => b.addEventListener('click', () => {
      day = addDays(day, Number(b.dataset.step) * (view === 'week' ? 7 : 1)); draw();
    }));
    qs(body, '[data-today]').addEventListener('click', () => { day = todayKey; draw(); });
    draw();
  });
}
