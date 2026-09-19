/**
 * The dashboard surfaces: the watchlist rows, the hero price block, the
 * intraday stat tiles and the connection pills.
 *
 * Everything is written with textContent. Asset names and symbols arrive from
 * third-party APIs, which makes them untrusted input no matter how reputable
 * the provider is - a name is a string someone else controls, and it is never
 * allowed to become markup.
 *
 * Direction is never carried by colour alone. Every change figure ships with an
 * arrow glyph and, for assistive technology, the word itself; the hue is the
 * third channel, not the only one.
 */

import { clear, el, num } from './dom.js';
import { icon } from './icons.js';
import {
  formatAge,
  formatClock,
  formatCompact,
  formatPercent,
  formatPrice,
  formatPriceDelta,
} from '../lib/format.js';
import { CONNECTION, CONNECTION_LABELS } from '../lib/model.js';

/** @param {number|null} changePct */
export function directionOf(changePct) {
  if (changePct === null || !Number.isFinite(changePct)) return 'flat';
  if (changePct > 0) return 'up';
  if (changePct < 0) return 'down';
  return 'flat';
}

const DIRECTION_GLYPH = { up: '▲', down: '▼', flat: '—' };
const DIRECTION_WORD = { up: 'עלייה', down: 'ירידה', flat: 'ללא שינוי' };
const DIRECTION_ICON = { up: 'trending-up', down: 'trending-down', flat: 'minus' };

/**
 * The watchlist: one dense row per asset, the selected one lit.
 *
 * @param {HTMLElement} container
 * @param {{asset: any, quote: any, age: number|null, flash?: string|null}[]} rows
 * @param {{selectedKey: string|null, onSelect: (key: string) => void,
 *   onRemove: (key: string) => void}} options
 */
export function renderWatchCards(container, rows, options) {
  clear(container);

  for (const row of rows) {
    const { asset, quote } = row;
    const direction = directionOf(quote?.changePct ?? null);

    const card = el('div', { class: `price-card dir-${direction}` });
    if (asset.key === options.selectedKey) card.classList.add('is-selected');
    // Set by the controller when the price moved since the last render.
    if (row.flash === 'up') card.classList.add('flash-up');
    if (row.flash === 'down') card.classList.add('flash-down');

    const button = el('button', {
      class: 'price-card-main',
      attrs: {
        type: 'button',
        'aria-pressed': asset.key === options.selectedKey ? 'true' : 'false',
      },
    });

    const head = el('div', { class: 'price-card-head' });
    head.append(
      el('span', { class: 'price-card-symbol', text: asset.displaySymbol, attrs: { dir: 'ltr' } }),
    );
    button.append(head);

    // The full name sits under the symbol, and is simply absent when no
    // provider has resolved one - never a placeholder that looks like a name.
    button.append(el('div', { class: 'price-card-name', text: asset.name ?? '—' }));

    const priceRow = el('div', { class: 'price-card-price' });
    priceRow.append(num(formatPrice(quote?.price ?? null), 'price-value'));
    if (asset.currency) priceRow.append(el('span', { class: 'price-currency', text: asset.currency }));
    button.append(priceRow);

    const changeRow = el('div', { class: 'price-card-change' });
    changeRow.append(
      el('span', {
        class: 'delta-glyph',
        text: DIRECTION_GLYPH[direction],
        attrs: { 'aria-hidden': 'true' },
      }),
    );
    changeRow.append(num(formatPercent(quote?.changePct ?? null)));
    changeRow.append(el('span', { class: 'visually-hidden', text: DIRECTION_WORD[direction] }));
    button.append(changeRow);

    button.addEventListener('click', () => options.onSelect(asset.key));
    card.append(button);

    const footer = el('div', { class: 'price-card-footer' });
    footer.append(
      el('span', { text: row.age === null ? 'ממתין לנתונים' : formatAge(row.age) }),
    );
    // The row is tight, so the badge is short; the full wording rides in the
    // tooltip and in the detail line above the chart.
    if (quote?.delayed) {
      footer.append(
        el('span', {
          class: 'badge badge-warn',
          text: 'עיכוב',
          attrs: { title: 'ייתכן עיכוב — הספק אינו מתחייב לזמן אמת' },
        }),
      );
    }

    const remove = el('button', {
      class: 'icon-button',
      attrs: {
        type: 'button',
        title: `הסרת ${asset.displaySymbol} מהמעקב`,
        'aria-label': `הסרת ${asset.displaySymbol} מהמעקב`,
      },
    });
    remove.append(icon('x', { size: 13 }));
    remove.addEventListener('click', (event) => {
      event.stopPropagation();
      options.onRemove(asset.key);
    });
    footer.append(remove);
    card.append(footer);

    container.append(card);
  }

  if (rows.length === 0) {
    container.append(
      el('p', { class: 'empty-note', text: 'רשימת המעקב ריקה. אפשר להוסיף נכס בעזרת החיפוש.' }),
    );
  }
}

/**
 * The hero: the one large number on the page, and the change beside it.
 *
 * @param {HTMLElement} priceHost
 * @param {HTMLElement} changeHost
 * @param {ReturnType<import('../lib/market.js').intradayStats>} stats
 * @param {any} asset
 */
export function renderHero(priceHost, changeHost, stats, asset) {
  clear(priceHost);
  clear(changeHost);

  priceHost.append(num(formatPrice(stats.price)));
  if (asset?.currency) {
    priceHost.append(el('span', { class: 'hero-price-currency', text: asset.currency }));
  }

  const direction = directionOf(stats.changePct);
  changeHost.className = `hero-change dir-${direction}`;

  const badge = el('span', { class: `badge badge-${direction}` });
  badge.append(icon(DIRECTION_ICON[direction], { size: 14 }));
  badge.append(num(formatPercent(stats.changePct)));
  changeHost.append(badge);

  changeHost.append(num(formatPriceDelta(stats.changeAbs), 'delta-abs'));
  changeHost.append(el('span', { class: 'visually-hidden', text: DIRECTION_WORD[direction] }));
}

/**
 * Intraday statistics. The explanation that used to sit under each tile now
 * lives in the tile's tooltip: at this density the prose was what made the row
 * unreadable, and the numbers are the point.
 *
 * @param {HTMLElement} container
 * @param {ReturnType<import('../lib/market.js').intradayStats>} stats
 */
export function renderIntradayStats(container, stats) {
  clear(container);

  const entries = [
    ['פתיחה', 'activity', formatPrice(stats.open), 'מחיר הפתיחה של המחזור הנוכחי כפי שדווח.'],
    ['גבוה', 'trending-up', formatPrice(stats.high), 'המחיר הגבוה ביותר במחזור הנוכחי.'],
    ['נמוך', 'trending-down', formatPrice(stats.low), 'המחיר הנמוך ביותר במחזור הנוכחי.'],
    [
      'מחזור',
      'bar-chart',
      formatCompact(stats.volume),
      'המחזור המצטבר כפי שדווח. אם הספק אינו מספק מחזור, מוצג המחזור שנצפה מאז פתיחת הדף.',
    ],
    [
      'עדכון אחרון',
      'clock',
      formatClock(stats.ts),
      'שעת ההודעה האחרונה שהתקבלה עבור הנכס, לפי שעון המכשיר שלך.',
    ],
  ];

  for (const [label, iconName, value, note] of entries) {
    const card = el('div', { class: 'stat-card', attrs: { title: note } });
    const labelRow = el('div', { class: 'stat-label' });
    labelRow.append(icon(iconName, { size: 12 }));
    labelRow.append(el('span', { text: label }));
    card.append(labelRow);

    const valueEl = el('div', { class: 'stat-value' });
    valueEl.append(num(value));
    card.append(valueEl);
    // Kept for assistive technology even though the tile hides it visually.
    card.append(el('p', { class: 'stat-note', text: note }));
    container.append(card);
  }
}

/**
 * A connection pill per source. The label says "מחובר" only when the feed is
 * actually delivering: an open socket that has gone silent reads as stale,
 * because a frozen price that looks live is the worst failure this dashboard
 * can have. The dot pulses only while healthy, so movement always means data.
 *
 * @param {HTMLElement} container
 * @param {{id: string, label: string, status: string, detail?: string,
 *   silenceMs?: number|null, stale?: boolean}[]} sources
 */
export function renderConnectionPills(container, sources) {
  clear(container);

  for (const source of sources) {
    const stale = source.stale === true && source.status === CONNECTION.CONNECTED;
    const state = stale ? 'stale' : source.status;

    const pill = el('div', { class: `status-pill status-${state}`, attrs: { role: 'status' } });
    pill.append(el('span', { class: 'status-dot', attrs: { 'aria-hidden': 'true' } }));
    pill.append(el('span', { class: 'status-source', text: source.label }));
    pill.append(
      el('span', {
        class: 'status-text',
        text: stale ? 'אין עדכונים' : (CONNECTION_LABELS[source.status] ?? source.status),
      }),
    );

    const detail = stale && source.silenceMs ? formatAge(source.silenceMs) : source.detail;
    if (detail) pill.append(el('span', { class: 'status-detail', text: detail }));

    container.append(pill);
  }
}
