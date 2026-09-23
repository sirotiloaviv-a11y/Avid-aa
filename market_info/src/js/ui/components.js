import { esc, ltr, trendClass } from '../dom.js';
import {
  formatPrice, formatPct, formatNumber, formatMultiple,
  formatDateTime, formatTime, formatRelative, tzLabel,
} from '../format.js';

export const ALERT_TYPE_LABELS = {
  price: 'שינוי במחיר',
  volume: 'נפח חריג',
  news: 'ידיעה חדשה',
};

export const ASSET_TYPE_LABELS = { stock: 'מניה', crypto: 'קריפטו' };

export const VOLUME_DISCLAIMER =
  'נתון סטטיסטי בלבד: הנפח גבוה מהממוצע. אין בו מידע על זהות הקונים או המוכרים, על כוונותיהם או על כיוון המחיר בהמשך.';

export function loadingView(label = 'טוען נתונים…') {
  return `<div class="state state-loading" role="status" aria-live="polite">
    <span class="spinner" aria-hidden="true"></span><span>${esc(label)}</span>
    <div class="skeleton"></div><div class="skeleton short"></div></div>`;
}

// Error titles distinguish "needs setup", quota limits and real faults.
const ERROR_TITLES = {
  not_configured: 'נדרשת הגדרה',
  rate_limited: 'מגבלת בקשות של ספק הנתונים',
  auth_failed: 'המפתח נדחה על ידי הספק',
  premium_required: 'הנתון דורש מסלול בתשלום',
  server_unreachable: 'השרת המקומי אינו זמין',
  network: 'תקלה בקבלת נתונים',
  upstream_unavailable: 'תקלה בקבלת נתונים',
  bad_response: 'תקלה בקבלת נתונים',
};

export function errorView(error) {
  const code = error?.code;
  const title = ERROR_TITLES[code] ?? 'לא ניתן היה לטעון את הנתונים.';
  const setup = code === 'not_configured' || code === 'auth_failed'
    ? '<a class="btn btn-outline" href="#/settings">הוראות הגדרה</a>' : '';
  return `<div class="state ${code === 'not_configured' ? 'state-setup' : 'state-error'}" role="alert" data-error-code="${esc(code ?? '')}">
    <strong>${esc(title)}</strong>
    <span>${esc(error?.message ?? 'שגיאה לא ידועה')}</span>
    <span class="row-actions"><button type="button" class="btn" data-retry>נסה שוב</button>${setup}</span></div>`;
}

// Shown in market mode for content that has no real source yet.
export function notConnectedView(what) {
  return `<div class="state state-empty" data-not-connected>
    <strong>טרם חובר</strong>
    <span>${esc(what)} אינם מחוברים עדיין למקור אמיתי במצב נתוני שוק. לא מוצג תוכן מומצא.</span>
    <span class="muted small">תוכן לדוגמה זמין במצב הדגמה (הגדרות ← מצב נתונים).</span></div>`;
}

export function emptyView(title, hint = '') {
  return `<div class="state state-empty"><strong>${esc(title)}</strong>${hint ? `<span>${hint}</span>` : ''}</div>`;
}

// Loads data into `el` with loading and error states and a retry button.
export async function loadInto(el, ctx, loader, onData, label) {
  el.innerHTML = loadingView(label);
  try {
    const data = await loader();
    if (!ctx.isActive()) return;
    onData(data);
  } catch (err) {
    if (!ctx.isActive()) return;
    el.innerHTML = errorView(err);
    el.querySelector('[data-retry]').addEventListener('click', () => loadInto(el, ctx, loader, onData, label));
  }
}

export function demoTag(text = 'הדגמה') {
  return `<span class="tag tag-demo">${esc(text)}</span>`;
}

export function changeBadge(asset) {
  if (asset.changePct === null || asset.changePct === undefined) return '<span class="change flat">—</span>';
  return `<span class="change ${trendClass(asset.changePct)}">${ltr(formatPct(asset.changePct))}</span>`;
}

export const DELAY_SHORT = { end_of_day: 'סוף יום', delayed: 'מושהה', realtime: 'זמן אמת' };

export const MARKET_REASON_LABELS = {
  weekend: 'סוף שבוע',
  pre_open: 'לפני פתיחת המסחר',
  after_close: 'אחרי סגירת המסחר',
  regular_hours: 'שעות מסחר רגילות',
  continuous: 'מסחר רציף 24/7',
};

// Source, data time and delay for one market datum, plus stale / partial
// flags. Returns '' for demo data, which is labeled elsewhere.
export function dataMeta(meta, tz, { compact = false } = {}) {
  if (!meta) return '';
  const when = meta.asOf ? formatDateTime(meta.asOf, tz) : 'לא ידוע';
  const flags = [];
  if (meta.stale) {
    flags.push(`<span class="tag tag-stale">${meta.staleReason === 'fetch_failed'
      ? 'נתון ישן — העדכון האחרון נכשל' : 'נתון ישן'}</span>`);
  }
  if (meta.partial && meta.changeBasis === 'previous_close') flags.push('<span class="tag tag-warn">יום מסחר נוכחי — נתון חלקי</span>');
  const fetched = meta.fetchedAt ? `עודכן לאחרונה מהספק: ${esc(formatDateTime(meta.fetchedAt, tz))}` : '';
  if (compact) {
    return `<span class="data-meta small">${esc(meta.source.name)} · ${esc(DELAY_SHORT[meta.delay] ?? meta.delay)} · ${esc(when)} ${flags.join('')}</span>`;
  }
  return `<div class="data-meta small">
    <span>מקור: <strong>${esc(meta.source.name)}</strong></span>
    <span>מועד הנתון: ${esc(when)}</span>
    <span>השהיה ידועה: ${esc(meta.delayLabel)}</span>
    ${fetched ? `<span>${fetched}</span>` : ''}
    ${flags.join('')}
    ${meta.warning ? `<span class="warn-text">${esc(meta.warning)}</span>` : ''}
    ${meta.source.attribution ? `<span class="attribution">${esc(meta.source.attribution)}</span>` : ''}
  </div>`;
}

export function rowError(error) {
  return `<span class="row-error" data-error-code="${esc(error.code)}">${esc(ERROR_TITLES[error.code] ?? 'שגיאה')}</span>`;
}

export function watchButton(symbol, watched, { compact = false } = {}) {
  const label = watched ? 'הסר ממעקב' : 'הוסף למעקב';
  return `<button type="button" class="btn ${watched ? 'btn-ghost' : 'btn-outline'} ${compact ? 'btn-sm' : ''}"
    data-watch="${esc(symbol)}" aria-pressed="${watched}" aria-label="${esc(label)} ${esc(symbol)}">${watched ? '★ ' : '☆ '}${label}</button>`;
}

export function assetRow(asset, { watched, selectable = false, selected = false, tz = 'UTC' } = {}) {
  const priced = typeof asset.price === 'number';
  const main = `<span class="asset-id">${ltr(asset.displaySymbol ?? asset.symbol, 'symbol')}<span class="asset-name">${esc(asset.name)}</span></span>
    <span class="asset-type">${esc(ASSET_TYPE_LABELS[asset.type])}</span>
    <span class="asset-price">${priced ? ltr(formatPrice(asset.price, asset.currency), 'num') : rowError(asset.error ?? { code: 'unknown' })}</span>
    ${priced ? changeBadge(asset) : '<span></span>'}
    ${asset.meta ? `<span class="asset-meta">${dataMeta(asset.meta, tz, { compact: true })}</span>` : ''}
    ${!priced && asset.error ? `<span class="asset-meta small muted">${esc(asset.error.message)}</span>` : ''}`;
  const opener = selectable
    ? `<button type="button" class="asset-main" data-select="${esc(asset.symbol)}" aria-pressed="${selected}">${main}</button>`
    : `<a class="asset-main" href="#/asset/${esc(asset.symbol)}">${main}</a>`;
  return `<li class="asset-row ${selected ? 'selected' : ''}">${opener}
    <span class="asset-actions">
      ${selectable ? `<a class="btn btn-sm btn-ghost" href="#/asset/${esc(asset.symbol)}">לעמוד הנכס</a>` : ''}
      ${watchButton(asset.symbol, watched, { compact: true })}
    </span></li>`;
}

export function newsCard(item, assetsBySymbol, tz) {
  const symbols = item.symbols.length
    ? item.symbols.map((s) => `<a class="chip" href="#/asset/${esc(s)}">${ltr(s)} ${esc(assetsBySymbol[s]?.name ?? '')}</a>`).join('')
    : '<span class="chip chip-muted">כללי</span>';
  return `<article class="news-card" data-news-id="${esc(item.id)}">
    <header>
      ${demoTag('ידיעת הדגמה')}
      <span class="tag">${esc(item.category)}</span>
      <time datetime="${new Date(item.publishedAt).toISOString()}" title="${esc(tzLabel(tz, item.publishedAt))}">
        ${esc(formatDateTime(item.publishedAt, tz))} · ${esc(formatRelative(item.publishedAt))}</time>
    </header>
    <h3>${esc(item.title)}</h3>
    <p>${esc(item.summary)}</p>
    <footer><span class="muted">מקור: תוכן הדגמה שנכתב עבור האבטיפוס — אינו מבוסס על כתבה אמיתית</span>
      <span class="chips">${symbols}</span></footer>
  </article>`;
}

export function eventRow(event, tz, { reminder = false, now = Date.now() } = {}) {
  const past = event.time < now;
  const soon = !past && event.time - now < 60 * 60 * 1000;
  const symbols = event.symbols.map((s) => `<a class="chip" href="#/asset/${esc(s)}">${ltr(s)}</a>`).join('');
  return `<li class="event-row ${past ? 'past' : ''}" data-event-id="${esc(event.id)}">
    <time class="event-time" datetime="${new Date(event.time).toISOString()}">${ltr(formatTime(event.time, tz), 'num')}</time>
    <div class="event-body">
      <div class="event-title">${esc(event.title)} ${demoTag('אירוע הדגמה')}</div>
      <div class="event-meta"><span class="tag">${esc(event.type)}</span>${symbols}
        ${past ? '<span class="muted">התקיים</span>' : ''}
        ${soon ? '<span class="tag tag-warn">בשעה הקרובה</span>' : ''}</div>
      <div class="muted small">${esc(event.description)}</div>
    </div>
    <button type="button" class="btn btn-sm ${reminder ? 'btn-ghost' : 'btn-outline'}" data-reminder="${esc(event.id)}"
      aria-pressed="${reminder}" ${past && !reminder ? 'disabled' : ''}>${reminder ? '🔔 תזכורת שמורה' : 'שמור תזכורת'}</button>
  </li>`;
}

export function alertDetails(alert, asset) {
  const t = alert.trigger;
  const currency = asset?.currency ?? 'USD';
  if (alert.type === 'price') {
    return {
      headline: `שינוי של ${ltr(formatPct(t.changePct))} במחיר`,
      rows: [
        ['מחיר קודם', ltr(formatPrice(t.fromPrice, currency))],
        ['מחיר חדש', ltr(formatPrice(t.toPrice, currency))],
        ['סף ההתראה', ltr(`±${t.thresholdPct}%`)],
      ],
      note: '',
    };
  }
  if (alert.type === 'volume') {
    return {
      headline: `נפח מסחר של פי ${ltr(formatMultiple(t.ratio))} מהממוצע ל-20 ימים`,
      rows: [
        ['נפח בפועל', ltr(formatNumber(t.volume))],
        ['ממוצע 20 ימים', ltr(formatNumber(t.avgVolume20))],
        ['סף ההתראה', `פי ${ltr(formatMultiple(t.thresholdMultiple))} מהממוצע`],
      ],
      note: VOLUME_DISCLAIMER,
    };
  }
  return {
    headline: `פורסמה ידיעה: ${esc(t.title)}`,
    rows: [['קטגוריה', esc(t.category)]],
    note: '',
  };
}

export function alertCard(alert, asset, tz, { read = false, compact = false } = {}) {
  const d = alertDetails(alert, asset);
  const newsLink = alert.type === 'news' && alert.trigger.newsId
    ? `<a class="btn btn-sm btn-ghost" href="#/news?symbol=${esc(alert.symbol)}">לידיעה</a>` : '';
  return `<article class="alert-card ${read ? 'read' : 'unread'} type-${esc(alert.type)}" data-alert-id="${esc(alert.id)}">
    <header>
      <span class="tag tag-type">${esc(ALERT_TYPE_LABELS[alert.type])}</span>
      <a class="chip" href="#/asset/${esc(alert.symbol)}">${ltr(alert.symbol)} ${esc(asset?.name ?? '')}</a>
      ${alert.manual ? demoTag('הופעל ידנית') : demoTag()}
      <time datetime="${new Date(alert.time).toISOString()}">${esc(formatDateTime(alert.time, tz))}</time>
      ${read ? '' : '<span class="unread-dot" aria-label="לא נקראה"></span>'}
    </header>
    <div class="alert-headline">${d.headline}</div>
    ${compact ? '' : `<dl class="trigger-data">${d.rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>
    ${d.note ? `<p class="note">${esc(d.note)}</p>` : ''}
    <div class="alert-actions">
      <button type="button" class="btn btn-sm btn-outline" data-toggle-read="${esc(alert.id)}">${read ? 'סמן כלא נקראה' : 'סמן כנקראה'}</button>
      ${newsLink}
    </div>`}
  </article>`;
}

export function statCard(label, valueHtml, sub = '', cls = '') {
  return `<div class="stat-card ${cls}"><div class="stat-label">${esc(label)}</div>
    <div class="stat-value">${valueHtml}</div>${sub ? `<div class="stat-sub">${sub}</div>` : ''}</div>`;
}

