/**
 * Pure selection logic: symbol search, date-range filtering, sorting and paging.
 *
 * Every view in the UI - stats, both charts, the table, the summary and both
 * exports - is derived from `selectRows()` with the same arguments, so they
 * cannot disagree about what "the current selection" means.
 *
 * Dates are handled as YYYY-MM-DD strings throughout. For that format
 * lexicographic comparison is chronological comparison, which keeps range
 * filtering exact and free of any timezone effect.
 */

/**
 * @param {{date: string, symbol: string}[]} rows Chronologically sorted rows.
 * @param {{symbol?: string|null, from?: string|null, to?: string|null}} selection
 * @returns {any[]} Rows matching the selection, still chronological.
 */
export function selectRows(rows, selection = {}) {
  const { symbol = null, from = null, to = null } = selection;
  if (!Array.isArray(rows) || rows.length === 0) return [];
  if (!symbol) return [];
  return rows.filter((row) => {
    if (row.symbol !== symbol) return false;
    if (from && row.date < from) return false;
    if (to && row.date > to) return false;
    return true;
  });
}

/**
 * First and last dates available for a symbol, ignoring any range filter.
 * @param {{date: string, symbol: string}[]} rows
 * @param {string} symbol
 * @returns {{firstDate: string, lastDate: string, count: number}|null}
 */
export function symbolBounds(rows, symbol) {
  let firstDate = null;
  let lastDate = null;
  let count = 0;
  for (const row of rows) {
    if (row.symbol !== symbol) continue;
    count += 1;
    if (firstDate === null || row.date < firstDate) firstDate = row.date;
    if (lastDate === null || row.date > lastDate) lastDate = row.date;
  }
  return count === 0 ? null : { firstDate, lastDate, count };
}

/**
 * Case-insensitive symbol search. Prefix matches rank before substring matches;
 * ties keep alphabetical order, so the list never jumps around unpredictably.
 * @param {string[]} symbols
 * @param {string} query
 * @returns {string[]}
 */
export function searchSymbols(symbols, query) {
  const needle = String(query ?? '').trim().toLowerCase();
  if (needle === '') return symbols.slice();
  const prefix = [];
  const contains = [];
  for (const symbol of symbols) {
    const haystack = symbol.toLowerCase();
    if (haystack.startsWith(needle)) prefix.push(symbol);
    else if (haystack.includes(needle)) contains.push(symbol);
  }
  return [...prefix, ...contains];
}

/**
 * Stable sort for the data table.
 * @template {{date: string, close: number, volume: number}} T
 * @param {T[]} rows
 * @param {'date'|'close'|'volume'} key
 * @param {'asc'|'desc'} direction
 * @returns {T[]} A new array; the input is not mutated.
 */
export function sortRows(rows, key, direction = 'asc') {
  const factor = direction === 'desc' ? -1 : 1;
  return rows.slice().sort((a, b) => {
    const left = a[key];
    const right = b[key];
    if (left === right) return 0;
    return (left < right ? -1 : 1) * factor;
  });
}

/**
 * @template T
 * @param {T[]} rows
 * @param {number} page 1-based; clamped into range.
 * @param {number} pageSize
 * @returns {{rows: T[], page: number, pageCount: number, total: number,
 *   firstIndex: number, lastIndex: number}}
 */
export function paginate(rows, page, pageSize) {
  const total = rows.length;
  const size = Math.max(1, Math.floor(pageSize) || 1);
  const pageCount = Math.max(1, Math.ceil(total / size));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pageCount);
  const start = (current - 1) * size;
  const slice = rows.slice(start, start + size);
  return {
    rows: slice,
    page: current,
    pageCount,
    total,
    firstIndex: total === 0 ? 0 : start + 1,
    lastIndex: start + slice.length,
  };
}

/**
 * Clamps a user-entered range to the dates a symbol actually has, and reports
 * whether the range is empty (`from` after `to`), which the UI surfaces as a
 * validation message rather than an empty chart with no explanation.
 * @param {{from?: string|null, to?: string|null}} range
 * @returns {{from: string|null, to: string|null, inverted: boolean}}
 */
export function normalizeRange(range = {}) {
  const from = range.from || null;
  const to = range.to || null;
  return { from, to, inverted: Boolean(from && to && from > to) };
}
