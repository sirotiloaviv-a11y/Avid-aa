import { esc, ltr, trendClass, qs } from '../dom.js';
import {
  formatPrice, formatSignedPrice, formatPct, formatCompact, formatNumber, formatDateTime, tzLabel,
} from '../format.js';
import {
  loadInto, newsCard, eventRow, emptyView, watchButton, demoTag, statCard, ASSET_TYPE_LABELS,
} from '../ui/components.js';
import { renderChart } from '../ui/chart.js';
import { RANGES } from './home.js';

export async function render(root, ctx) {
  const tz = ctx.tz();
  const { symbol } = ctx.params;
  root.innerHTML = '<div id="asset-page"></div>';
  const page = qs(root, '#asset-page');

  loadInto(page, ctx, () => Promise.all([ctx.provider.getAsset(symbol), ctx.provider.getAssets()]), ([asset, all]) => {
    if (!asset) {
      page.innerHTML = `<h1>נכס לא נמצא</h1>${emptyView(`הסימול ${symbol} אינו קיים בנתוני ההדגמה.`,
        '<a href="#/assets">חזרה לרשימת הנכסים</a>')}`;
      return;
    }
    const bySymbol = Object.fromEntries(all.map((a) => [a.symbol, a]));
    let range = 30;

    const drawHeader = () => {
      qs(page, '#asset-head').innerHTML = `
        <div>
          <a href="#/assets" class="link small">→ חזרה לרשימת הנכסים</a>
          <h1>${ltr(asset.symbol, 'symbol')} ${esc(asset.name)}</h1>
          <div class="chips"><span class="tag">${esc(ASSET_TYPE_LABELS[asset.type])}</span>
            <span class="tag">${esc(asset.sector)}</span>${demoTag('נכס בדיוני')}</div>
        </div>
        <div class="asset-head-actions">${watchButton(asset.symbol, ctx.store.isWatched(asset.symbol))}</div>`;
      qs(page, '[data-watch]').addEventListener('click', () => {
        ctx.store.toggleWatch(asset.symbol);
        drawHeader();
      });
    };

    page.innerHTML = `
      <div class="page-head asset-head" id="asset-head"></div>
      <div class="stats">
        ${statCard('מחיר הדגמה אחרון', ltr(formatPrice(asset.price, asset.currency), 'num'),
          `נכון ל-${esc(formatDateTime(asset.asOf, tz))}`)}
        ${statCard('שינוי מהסגירה הקודמת', `${ltr(formatSignedPrice(asset.change, asset.currency), trendClass(asset.change))}
          ${ltr(formatPct(asset.changePct), trendClass(asset.changePct))}`, `סגירה קודמת: ${ltr(formatPrice(asset.previousClose, asset.currency))}`,
          trendClass(asset.changePct))}
        ${statCard('נפח מסחר (יום אחרון)', ltr(formatCompact(asset.volume), 'num'), ltr(formatNumber(asset.volume)))}
        ${statCard('נפח ממוצע ל-20 ימים', ltr(formatCompact(asset.avgVolume20), 'num'), ltr(formatNumber(asset.avgVolume20)))}
      </div>
      <section class="panel">
        <div class="panel-head"><h2>גרף מחיר ונפח</h2><span class="seg" id="ranges"></span></div>
        <p class="muted small">ציר הזמן לפי ${esc(tzLabel(tz))}. ${asset.type === 'stock'
          ? 'נר יומי נסגר ב-20:00 UTC, ימי מסחר בלבד.' : 'נר יומי נסגר ב-00:00 UTC, כל ימות השבוע.'}</p>
        <div id="asset-chart"></div>
      </section>
      <div class="grid-2">
        <section class="panel"><div class="panel-head"><h2>חדשות לדוגמה</h2>
          <a class="link" href="#/news?symbol=${esc(asset.symbol)}">לכל הידיעות על הנכס</a></div>
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
      loadInto(box, ctx, () => ctx.provider.getPriceHistory(asset.symbol, range), (bars) => {
        box.innerHTML = '';
        renderChart(box, bars, { currency: asset.currency, tz });
      }, 'טוען גרף…');
    };
    drawChart();

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
