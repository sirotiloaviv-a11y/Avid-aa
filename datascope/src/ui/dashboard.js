/**
 * The dashboard surfaces: the watchlist cards, the intraday statistics and the
 * connection pills.
 *
 * Everything is written with textContent. Asset names and symbols arrive from
 * third-party APIs, which makes them untrusted input no matter how reputable the
 * provider is - a name is a string someone else controls, and it is never
 * allowed to become markup.
 *
 * Cards are rebuilt from state on each render rather than patched in place. At
 * a handful of watched assets that is cheap, and it removes a whole class of bug
 * where a card keeps a stale value because one update path forgot to clear it.
 */

import { clear, el, num } from './dom.js';
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
function directionOf(changePct) {
  if (changePct === null || !Number.isFinite(changePct)) return 'flat';
  if (changePct > 0) return 'up';
  if (changePct < 0) return 'down';
  return 'flat';
}

const DIRECTION_GLYPH = { up: '▲', down: '▼', flat: '■' };
const DIRECTION_WORD = { up: 'עלייה', down: 'ירידה', flat: 'ללא שינוי' };

/**
 * The watchlist: one card per asset, the selected one marked.
 *
 * @param {HTMLElement} container
 * @param {{asset: any, quote: any, age: number|null}[]} rows
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

    const button = el('button', {
      class: 'price-card-main',
      attrs: {
        type: 'button',
        'aria-pressed': asset.key === options.selectedKey ? 'true' : 'false',
      },
    });

    const head = el('div', { class: 'price-card-head' });
    head.append(el('span', { class: 'price-card-symbol', text: asset.displaySymbol, attrs: { dir: 'ltr' } }));
    head.append(
      el('span', {
        class: `asset-chip chip-${asset.assetClass}`,
        text: asset.assetClass === 'crypto' ? 'קריפטו' : 'מניה',
      }),
    );
    button.append(head);

    // The full name sits under the symbol, and is simply absent when no provider
    // has resolved one - never a placeholder that looks like a name.
    button.append(
      el('div', {
        class: 'price-card-name',
        text: asset.name ?? '—',
        attrs: asset.name ? {} : { 'aria-label': 'שם הנכס טרם נטען' },
      }),
    );

    const priceRow = el('div', { class: 'price-card-price' });
    priceRow.append(num(formatPrice(quote?.price ?? null), 'price-value'));
    if (asset.currency) {
      priceRow.append(el('span', { class: 'price-currency', text: asset.currency }));
    }
    button.append(priceRow);

    const changeRow = el('div', { class: 'price-card-change' });
    changeRow.append(
      el('span', { class: 'delta-glyph', text: DIRECTION_GLYPH[direction], attrs: { 'aria-hidden': 'true' } }),
    );
    changeRow.append(num(formatPercent(quote?.changePct ?? null)));
    changeRow.append(num(formatPriceDelta(quote?.changeAbs ?? null), 'delta-abs'));
    // Direction is carried by a word and a glyph as well as by colour, so it
    // still reads in monochrome and for colour-blind viewers.
    changeRow.append(el('span', { class: 'visually-hidden', text: DIRECTION_WORD[direction] }));
    button.append(changeRow);

    button.addEventListener('click', () => options.onSelect(asset.key));
    card.append(button);

    const footer = el('div', { class: 'price-card-footer' });
    footer.append(
      el('span', {
        class: 'price-card-age',
        text: row.age === null ? 'ממתין לנתונים' : formatAge(row.age),
      }),
    );
    if (quote?.delayed) footer.append(el('span', { class: 'badge-delayed', text: 'ייתכן עיכוב' }));

    const remove = el('button', {
      class: 'icon-button',
      text: '✕',
      attrs: { type: 'button', title: `הסרת ${asset.displaySymbol} מהמעקב`, 'aria-label': `הסרת ${asset.displaySymbol} מהמעקב` },
    });
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
      el('p', { class: 'empty-note', text: 'רשימת המעקב ריקה. אפשר להוסיף נכס בעזרת החיפוש שלמעלה.' }),
    );
  }
}

/**
 * Intraday statistics for the selected asset.
 *
 * @param {HTMLElement} container
 * @param {ReturnType<import('../lib/market.js').intradayStats>} stats
 * @param {any} asset
 */
export function renderIntradayStats(container, stats, asset) {
  clear(container);

  const currency = asset?.currency ? ` ${asset.currency}` : '';
  const entries = [
    ['מחיר אחרון', formatPrice(stats.price) + currency, 'המחיר האחרון שהתקבל מהספק.'],
    [
      'שינוי יומי',
      `${formatPercent(stats.changePct)} · ${formatPriceDelta(stats.changeAbs)}`,
      'השינוי מול מחיר הפתיחה או הסגירה הקודמת, לפי מה שהספק מדווח.',
    ],
    ['פתיחה', formatPrice(stats.open), 'מחיר הפתיחה של המחזור הנוכחי כפי שדווח.'],
    ['גבוה', formatPrice(stats.high), 'המחיר הגבוה ביותר במחזור הנוכחי.'],
    ['נמוך', formatPrice(stats.low), 'המחיר הנמוך ביותר במחזור הנוכחי.'],
    [
      'מחזור',
      formatCompact(stats.volume),
      'המחזור המצטבר כפי שדווח על ידי הספק. אם הספק אינו מספק מחזור, מוצג המחזור שנצפה מאז פתיחת הדף.',
    ],
    [
      'עדכון אחרון',
      formatClock(stats.ts),
      'שעת ההודעה האחרונה שהתקבלה עבור הנכס, לפי שעון המכשיר שלך.',
    ],
  ];

  for (const [label, value, note] of entries) {
    const card = el('div', { class: 'stat-card' });
    card.append(el('div', { class: 'stat-label', text: label }));
    const valueEl = el('div', { class: 'stat-value' });
    valueEl.append(num(value));
    card.append(valueEl);
    card.append(el('p', { class: 'stat-note', text: note }));
    container.append(card);
  }
}

/**
 * A connection pill. The label says "מחובר" only when the feed is actually
 * delivering: an open socket that has gone silent reads as stale, because a
 * frozen price that looks live is the worst failure this dashboard can have.
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

    const pill = el('div', { class: `status-pill status-${state}` });
    pill.append(el('span', { class: 'status-dot', attrs: { 'aria-hidden': 'true' } }));
    pill.append(el('span', { class: 'status-source', text: source.label }));
    pill.append(
      el('span', {
        class: 'status-text',
        text: stale ? 'מחובר · אין עדכונים' : CONNECTION_LABELS[source.status] ?? source.status,
      }),
    );

    const detail = stale && source.silenceMs ? formatAge(source.silenceMs) : source.detail;
    if (detail) pill.append(el('span', { class: 'status-detail', text: detail }));

    pill.setAttribute('role', 'status');
    container.append(pill);
  }
}
