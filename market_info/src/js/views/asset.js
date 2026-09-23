import { esc, ltr, trendClass, qs } from '../dom.js';
import {
  formatPrice, formatSignedPrice, formatPct, formatCompact, formatNumber, formatDateTime, tzLabel,
} from '../format.js';
import {
  loadInto, newsCard, eventRow, emptyView, watchButton, demoTag, statCard, dataMeta, notConnectedView,
  ASSET_TYPE_LABELS, MARKET_REASON_LABELS,
} from '../ui/components.js';
import { renderChart } from '../ui/chart.js';
import { RANGES } from './home.js';

const CHANGE_LABELS = {
  previous_close: 'שינוי מהסגירה הקודמת',
  '24h': 'שינוי ב-24 השעות האחרונות',
};

function numOrMissing(value, fmt) {
  return value === null || value === undefined ? '<span class="muted">אין נתון במקור</span>' : fmt(value);
}

function statCards(asset, tz, market) {
  const m = asset.meta;
  const priceLabel = !market ? 'מחיר הדגמה אחרון'
    : asset.type === 'stock' ? 'מחיר סגירה אחרון' : 'מחיר אחרון (מושהה)';
  const priceSub = market
    ? `${esc(m.source.name)} · ${esc(m.asOf ? formatDateTime(m.asOf, tz) : 'מועד לא ידוע')}`
    : `נכון ל-${esc(formatDateTime(asset.asOf, tz))}`;
  const changeValue = asset.change === null || asset.change === undefined
    ? '<span class="muted">אין נתון להשוואה</span>'
    : `${ltr(formatSignedPrice(asset.change, asset.currency), trendClass(asset.change))}
       ${ltr(formatPct(asset.changePct), trendClass(asset.changePct))}`;
  const changeSub = asset.previousClose === null || asset.previousClose === undefined ? ''
    : `${m?.changeBasis === '24h' ? 'מחיר לפני 24 שעות' : 'סגירה קודמת'}: ${ltr(formatPrice(asset.previousClose, asset.currency))}`;
  const volumeLabel = m?.volumeLabel ?? 'נפח מסחר (יום אחרון)';
  const avgLabel = market && asset.type === 'crypto' ? null : 'נפח ממוצע ל-20 ימים';
  return `<div class="stats">
    ${statCard(priceLabel, ltr(formatPrice(asset.price, asset.currency), 'num'), priceSub)}
    ${statCard(CHANGE_LABELS[m?.changeBasis ?? 'previous_close'], changeValue, changeSub, trendClass(asset.changePct ?? 0))}
    ${statCard(volumeLabel, numOrMissing(asset.volume, (v) => ltr(formatCompact(v), 'num')),
      asset.volume === null || asset.volume === undefined ? '' : ltr(formatNumber(Math.round(asset.volume))))}
    ${avgLabel ? statCard(avgLabel, numOrMissing(asset.avgVolume20, (v) => ltr(formatCompact(v), 'num')),
      market ? 'מחושב מ-20 הימים שלפני היום האחרון' : ltr(formatNumber(asset.avgVolume20)))
      : statCard('מצב המסחר', 'רציף', esc(MARKET_REASON_LABELS.continuous))}
  </div>`;
}

export async function render(root, ctx) {
  const tz = ctx.tz();
  const market = ctx.mode === 'market';
  const { symbol } = ctx.params;
  root.innerHTML = '<div id="asset-page"></div>';
  const page = qs(root, '#asset-page');

  loadInto(page, ctx, () => Promise.all([ctx.provider.getAsset(symbol), market ? [] : ctx.provider.getAssets()]), ([asset, all]) => {
    if (!asset) {
      page.innerHTML = `<h1>נכס לא נמצא</h1>${emptyView(
        market ? `הסימול ${symbol} לא נמצא אצל ספק הנתונים, או שאינו בפורמט תקין.` : `הסימול ${symbol} אינו קיים בנתוני ההדגמה.`,
        '<a href="#/assets">חזרה לרשימת הנכסים</a>')}`;
      return;
    }
    const bySymbol = Object.fromEntries(all.map((a) => [a.symbol, a]));
    let range = 30;

    const drawHeader = () => {
      const tags = market
        ? `<span class="tag">${esc(ASSET_TYPE_LABELS[asset.type])}</span>`
        : `<span class="tag">${esc(ASSET_TYPE_LABELS[asset.type])}</span><span class="tag">${esc(asset.sector)}</span>${demoTag('נכס בדיוני')}`;
      qs(page, '#asset-head').innerHTML = `
        <div>
          <a href="#/assets" class="link small">→ חזרה לרשימת הנכסים</a>
          <h1>${ltr(asset.displaySymbol ?? asset.symbol, 'symbol')} ${esc(asset.name)}</h1>
          <div class="chips">${tags}</div>
        </div>
        <div class="asset-head-actions">${watchButton(asset.symbol, ctx.store.isWatched(asset.symbol))}</div>`;
      qs(page, '[data-watch]').addEventListener('click', () => {
        ctx.store.toggleWatch(asset.symbol);
        drawHeader();
      });
    };

    const chartNote = market
      ? (asset.type === 'stock'
        ? 'נר יומי לכל יום מסחר, כפי שהתקבל מהספק. ימים שחסרים במקור אינם מושלמים.'
        : 'נקודת מחיר יומית (ללא נרות) ונפח 24 שעות, כפי שהתקבלו מהספק.')
      : (asset.type === 'stock' ? 'נר יומי נסגר ב-20:00 UTC, ימי מסחר בלבד.' : 'נר יומי נסגר ב-00:00 UTC, כל ימות השבוע.');
    const session = market && asset.type === 'stock'
      ? `<p class="small">מצב המסחר בארה״ב כעת: <strong>${asset.meta.marketState === 'open' ? 'פתוח' : 'סגור'}</strong>
          (${esc(MARKET_REASON_LABELS[asset.meta.marketReason] ?? '')}; לפי שעות רגילות, ללא חגים).
          ${asset.meta.marketState === 'closed' ? 'המחיר המוצג הוא מחיר הסגירה האחרון — זה אינו מצב תקלה.' : ''}</p>` : '';

    page.innerHTML = `
      <div class="page-head asset-head" id="asset-head"></div>
      ${market ? `<section class="panel">${dataMeta(asset.meta, tz)}${session}</section>` : ''}
      ${statCards(asset, tz, market)}
      <section class="panel">
        <div class="panel-head"><h2>גרף מחיר ונפח</h2><span class="seg" id="ranges"></span></div>
        <p class="muted small">ציר הזמן לפי ${esc(tzLabel(tz))}. ${esc(chartNote)}</p>
        <div id="chart-meta"></div>
        <div id="asset-chart"></div>
      </section>
      <div class="grid-2">
        <section class="panel"><div class="panel-head"><h2>${market ? 'חדשות' : 'חדשות לדוגמה'}</h2>
          ${market ? '' : `<a class="link" href="#/news?symbol=${esc(asset.symbol)}">לכל הידיעות על הנכס</a>`}</div>
          <div id="asset-news"></div></section>
        <section class="panel"><div class="panel-head"><h2>אירועים קשורים</h2></div>
          <div id="asset-events"></div></section>
      </div>`;
    drawHeader();

    const drawChart = () => {
      qs(page, '#ranges').innerHTML = RANGES.map((r) => `<button type="button" class="${r.bars === range ? 'on' : ''}"
        aria-pressed="${r.bars === range}" data-range="${r.bars}">${esc(r.label)}</button>`).join('');
      page.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => {
        range = Number(b.dataset.range);
        drawChart();
      }));
      const box = qs(page, '#asset-chart');
      const loader = market
        ? () => ctx.provider.getHistory(asset.symbol)
        : () => ctx.provider.getPriceHistory(asset.symbol, range).then((bars) => ({ bars }));
      loadInto(box, ctx, loader, (h) => {
        box.innerHTML = '';
        const bars = h.bars.slice(-range);
        if (h.meta) qs(page, '#chart-meta').innerHTML = dataMeta(h.meta, tz, { compact: true });
        if (h.bars.length < range && market) {
          qs(page, '#chart-meta').insertAdjacentHTML('beforeend',
            `<p class="muted small">הספק החזיר ${h.bars.length} נקודות בלבד; מוצג מה שהתקבל.</p>`);
        }
        renderChart(box, bars, { currency: asset.currency, tz, volumeLabel: asset.meta?.volumeLabel ?? 'נפח' });
      }, 'טוען גרף…');
    };
    drawChart();

    if (market) {
      qs(page, '#asset-news').innerHTML = notConnectedView('חדשות');
      qs(page, '#asset-events').innerHTML = notConnectedView('אירועים');
      return;
    }

    loadInto(qs(page, '#asset-news'), ctx, () => ctx.provider.getNews({ symbol: asset.symbol }), (items) => {
      qs(page, '#asset-news').innerHTML = items.length
        ? `<div class="stack">${items.slice(0, 4).map((n) => newsCard(n, bySymbol, tz)).join('')}</div>`
        : emptyView('אין ידיעות הדגמה על נכס זה');
    });

    const drawEvents = (list) => {
      const el = qs(page, '#asset-events');
      const mine = list.filter((e) => e.symbols.includes(asset.symbol));
      if (!mine.length) { el.innerHTML = emptyView('אין אירועים מתוכננים לנכס זה'); return; }
      el.innerHTML = `<p class="muted small">השעות לפי ${esc(tzLabel(tz))}</p><ul class="event-list">${mine.map((e) =>
        `<li class="event-day-label">${esc(formatDateTime(e.time, tz))}</li>${eventRow(e, tz, { reminder: ctx.store.hasReminder(e.id) })}`).join('')}</ul>`;
      el.querySelectorAll('[data-reminder]').forEach((b) => b.addEventListener('click', () => {
        ctx.store.toggleReminder(b.dataset.reminder);
        drawEvents(list);
      }));
    };
    loadInto(qs(page, '#asset-events'), ctx, () => ctx.provider.getEvents(), drawEvents);
  });
}
