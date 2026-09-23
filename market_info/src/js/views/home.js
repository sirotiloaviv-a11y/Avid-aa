import { esc, ltr, trendClass, qs } from '../dom.js';
import { formatPct, formatPrice, formatCompact, formatDateTime, tzLabel, dateKey } from '../format.js';
import {
  loadInto, statCard, assetRow, newsCard, alertCard, emptyView, demoTag,
} from '../ui/components.js';
import { renderChart } from '../ui/chart.js';

export const RANGES = [
  { bars: 7, label: 'שבוע' },
  { bars: 30, label: 'חודש' },
  { bars: 90, label: '3 חודשים' },
];

export async function render(root, ctx) {
  const tz = ctx.tz();
  root.innerHTML = `
    <div class="page-head"><h1>דף הבית</h1>
      <span class="muted small">אזור זמן: ${esc(tzLabel(tz))}</span></div>
    <section aria-labelledby="h-overview"><h2 id="h-overview" class="sr-only">מצב שוק</h2>
      <div id="overview"></div></section>
    <div class="grid-2">
      <section class="panel" aria-labelledby="h-watch">
        <div class="panel-head"><h2 id="h-watch">רשימת מעקב</h2><a href="#/assets" class="link">ניהול נכסים</a></div>
        <div id="watchlist"></div></section>
      <section class="panel" aria-labelledby="h-chart">
        <div class="panel-head"><h2 id="h-chart">גרף הנכס הנבחר</h2><span id="chart-ranges" class="seg"></span></div>
        <div id="chart-area"></div></section>
    </div>
    <div class="grid-3">
      <section class="panel" aria-labelledby="h-news">
        <div class="panel-head"><h2 id="h-news">חדשות אחרונות</h2><a href="#/news" class="link">לכל החדשות</a></div>
        <div id="home-news"></div></section>
      <section class="panel" aria-labelledby="h-events">
        <div class="panel-head"><h2 id="h-events">אירועים קרובים</h2><a href="#/events" class="link">ללוח האירועים</a></div>
        <div id="home-events"></div></section>
      <section class="panel" aria-labelledby="h-alerts">
        <div class="panel-head"><h2 id="h-alerts">התראות מידע אחרונות</h2><a href="#/alerts" class="link">למרכז ההתראות</a></div>
        <div id="home-alerts"></div></section>
    </div>`;

  let assetsBySymbol = {};
  let range = 30;

  loadInto(qs(root, '#overview'), ctx, () => ctx.provider.getMarketOverview(), (o) => {
    const group = (g) => `${ltr(formatPct(g.avgChangePct), trendClass(g.avgChangePct))}`;
    qs(root, '#overview').innerHTML = `<div class="stats">
      ${statCard('מניות (ממוצע שינוי יומי)', group(o.stocks), `${o.stocks.up} עולות · ${o.stocks.down} יורדות`, trendClass(o.stocks.avgChangePct))}
      ${statCard('קריפטו (ממוצע שינוי יומי)', group(o.crypto), `${o.crypto.up} עולים · ${o.crypto.down} יורדים`, trendClass(o.crypto.avgChangePct))}
      ${statCard('רוחב שוק', `${ltr(`${o.breadth.up} / ${o.breadth.down}`)}`, 'נכסים בעלייה / בירידה')}
      ${statCard('עדכון נתוני ההדגמה', esc(formatDateTime(o.asOf, tz)), 'נתונים סטטיים — לא מתעדכנים בזמן אמת')}
    </div>`;
  });

  const drawWatchlist = (all) => {
    const el = qs(root, '#watchlist');
    const state = ctx.store.get();
    const list = state.watchlist.map((s) => assetsBySymbol[s]).filter(Boolean);
    if (!list.length) {
      el.innerHTML = emptyView('רשימת המעקב ריקה', '<a href="#/assets">הוסיפו נכסים ממסך הנכסים</a>');
      qs(root, '#chart-area').innerHTML = emptyView('לא נבחר נכס', 'הוסיפו נכס לרשימת המעקב כדי לראות גרף.');
      qs(root, '#chart-ranges').innerHTML = '';
      return;
    }
    let selected = state.selectedSymbol;
    if (!list.some((a) => a.symbol === selected)) selected = list[0].symbol;
    el.innerHTML = `<ul class="asset-list">${list.map((a) => assetRow(a, {
      watched: true, selectable: true, selected: a.symbol === selected })).join('')}</ul>`;
    el.querySelectorAll('[data-select]').forEach((b) => b.addEventListener('click', () => {
      ctx.store.selectSymbol(b.dataset.select);
      drawWatchlist(all);
    }));
    el.querySelectorAll('[data-watch]').forEach((b) => b.addEventListener('click', () => {
      ctx.store.toggleWatch(b.dataset.watch);
      drawWatchlist(all);
    }));
    drawChart(assetsBySymbol[selected]);
  };

  const drawChart = (asset) => {
    const rangesEl = qs(root, '#chart-ranges');
    rangesEl.innerHTML = RANGES.map((r) => `<button type="button" class="${r.bars === range ? 'on' : ''}"
      aria-pressed="${r.bars === range}" data-range="${r.bars}">${esc(r.label)}</button>`).join('');
    rangesEl.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => {
      range = Number(b.dataset.range);
      drawChart(asset);
    }));
    const area = qs(root, '#chart-area');
    area.innerHTML = `<div class="chart-head">
        <div><a href="#/asset/${esc(asset.symbol)}" class="chart-title">${ltr(asset.symbol, 'symbol')} ${esc(asset.name)}</a> ${demoTag()}</div>
        <div>${ltr(formatPrice(asset.price, asset.currency), 'num big')}
          <span class="change ${trendClass(asset.changePct)}">${ltr(formatPct(asset.changePct))}</span></div>
        <div class="muted small">נפח אחרון: ${ltr(formatCompact(asset.volume))}</div>
      </div><div id="chart-box"></div>`;
    const box = qs(area, '#chart-box');
    loadInto(box, ctx, () => ctx.provider.getPriceHistory(asset.symbol, range), (bars) => {
      box.innerHTML = '';
      renderChart(box, bars, { currency: asset.currency, tz });
    }, 'טוען גרף…');
  };

  loadInto(qs(root, '#watchlist'), ctx, () => ctx.provider.getAssets(), (all) => {
    assetsBySymbol = Object.fromEntries(all.map((a) => [a.symbol, a]));
    drawWatchlist(all);
    loadNews();
    loadAlerts();
  });

  const loadNews = () => loadInto(qs(root, '#home-news'), ctx, () => ctx.provider.getNews(), (items) => {
    const el = qs(root, '#home-news');
    el.innerHTML = items.length
      ? `<div class="stack compact">${items.slice(0, 4).map((n) => newsCard(n, assetsBySymbol, tz)).join('')}</div>`
      : emptyView('אין ידיעות להצגה');
  });

  loadInto(qs(root, '#home-events'), ctx, () => ctx.provider.getEvents({ from: Date.now() }), (list) => {
    const el = qs(root, '#home-events');
    if (!list.length) { el.innerHTML = emptyView('אין אירועים קרובים'); return; }
    el.innerHTML = `<p class="muted small">השעות לפי ${esc(tzLabel(tz))}</p>
      <ul class="event-list">${list.slice(0, 5).map((e) => `<li class="mini-event">
        <span class="muted">${esc(formatDateTime(e.time, tz))}</span>
        <a href="#/events?view=day&date=${dateKey(e.time, tz)}">${esc(e.title)}</a></li>`).join('')}</ul>`;
  });

  const loadAlerts = () => loadInto(qs(root, '#home-alerts'), ctx, () => ctx.getAllAlerts(), (all) => {
    const el = qs(root, '#home-alerts');
    const list = ctx.visibleAlerts(all).slice(0, 4);
    const read = ctx.store.get().readAlerts;
    el.innerHTML = list.length
      ? `<div class="stack compact">${list.map((a) => alertCard(a, assetsBySymbol[a.symbol], tz, { read: read[a.id], compact: true })).join('')}</div>`
      : emptyView('אין התראות להצגה', 'ייתכן שסוגי ההתראות כבויים בהגדרות.');
  });
}
