/**
 * The data table: sortable headers, paging, and the same rows the charts and the
 * statistics were computed from.
 *
 * It doubles as the accessible table view for both charts - every value that a
 * chart only shows as a mark is readable here as text.
 */

import { clear, el, num } from './dom.js';
import { formatDate, formatInteger, formatPrice } from '../lib/format.js';

/** @type {{key: 'date'|'close'|'volume', label: string}[]} */
const COLUMNS = [
  { key: 'date', label: 'תאריך' },
  { key: 'close', label: 'מחיר סגירה' },
  { key: 'volume', label: 'מחזור' },
];

/**
 * @param {HTMLElement} container
 * @param {{rows: any[], page: number, pageCount: number, total: number,
 *   firstIndex: number, lastIndex: number}} pageData
 * @param {{sortKey: string, sortDirection: 'asc'|'desc', symbol: string}} view
 * @param {(key: string) => void} onSort
 */
export function renderTable(container, pageData, view, onSort) {
  clear(container);

  const table = el('table', { class: 'data-table' });
  const caption = el('caption', {
    text: `תצפיות עבור ${view.symbol} — מוצגות שורות ${pageData.firstIndex}–${pageData.lastIndex} מתוך ${formatInteger(
      pageData.total,
    )}`,
  });
  table.append(caption);

  const head = el('thead');
  const headRow = el('tr');
  for (const column of COLUMNS) {
    const isSorted = view.sortKey === column.key;
    const cell = el('th', { attrs: { scope: 'col' } });
    cell.setAttribute('aria-sort', isSorted ? (view.sortDirection === 'asc' ? 'ascending' : 'descending') : 'none');

    const button = el('button', {
      class: 'sort-button',
      attrs: { type: 'button', 'data-sort-key': column.key },
    });
    button.append(el('span', { text: column.label }));
    button.append(
      el('span', {
        class: 'sort-arrow',
        attrs: { 'aria-hidden': 'true' },
        text: isSorted ? (view.sortDirection === 'asc' ? '▲' : '▼') : '↕',
      }),
    );
    const direction = isSorted && view.sortDirection === 'asc' ? 'יורד' : 'עולה';
    button.setAttribute('title', `מיון לפי ${column.label} בסדר ${direction}`);
    button.addEventListener('click', () => onSort(column.key));
    cell.append(button);
    headRow.append(cell);
  }
  head.append(headRow);
  table.append(head);

  const body = el('tbody');
  for (const row of pageData.rows) {
    const tr = el('tr');
    tr.append(el('td', { children: [num(formatDate(row.date))] }));
    tr.append(el('td', { class: 'cell-number', children: [num(formatPrice(row.close))] }));
    tr.append(el('td', { class: 'cell-number', children: [num(formatInteger(row.volume))] }));
    body.append(tr);
  }
  table.append(body);
  container.append(table);
}
