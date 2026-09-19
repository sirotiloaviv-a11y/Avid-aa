/**
 * DataScope controller.
 *
 * One state object, one `render()`. Every panel - statistics, both charts, the
 * summary, the table and both exports - is derived from the same
 * `selectRows(state)` result on every render, which is what keeps them from ever
 * showing different periods or different numbers.
 *
 * Nothing here writes to localStorage, sessionStorage, IndexedDB or cookies: the
 * imported data lives in memory for the life of the tab and is gone on reload.
 */

import { validateDataset, LIMITS } from './lib/validate.js';
import { computeStats } from './lib/stats.js';
import {
  normalizeRange,
  paginate,
  searchSymbols,
  selectRows,
  sortRows,
  symbolBounds,
} from './lib/selection.js';
import { buildSummary } from './lib/summary.js';
import { buildCsv, buildTextReport, safeFileName } from './lib/exporters.js';
import { DEMO_FILE_NAME, generateDemoCsv } from './lib/demo.js';
import { formatBytes, formatDate, formatInteger, todayIso } from './lib/format.js';
import { byId, clear, downloadText, el, show } from './ui/dom.js';
import { renderPriceChart, renderVolumeChart } from './ui/charts.js';
import { renderTable } from './ui/table.js';
import {
  renderSourceBanner,
  renderStats,
  renderSummary,
  renderValidationReport,
} from './ui/panels.js';

/** @typedef {'asc'|'desc'} SortDirection */

const state = {
  /** @type {any} */
  dataset: null,
  isDemo: false,
  /** @type {string|null} */
  selectedSymbol: null,
  /** @type {string|null} */
  from: null,
  /** @type {string|null} */
  to: null,
  /** @type {'date'|'close'|'volume'} */
  sortKey: 'date',
  /** @type {SortDirection} */
  sortDirection: 'asc',
  page: 1,
  pageSize: 25,
};

const ui = {};

function cacheElements() {
  const ids = [
    'dropzone',
    'file-input',
    'file-button',
    'load-demo',
    'download-sample',
    'clear-data',
    'loading',
    'loading-text',
    'status-message',
    'validation-report',
    'empty-state',
    'analysis',
    'source-banner',
    'symbol-search',
    'symbol-select',
    'symbol-count',
    'date-from',
    'date-to',
    'reset-range',
    'range-message',
    'no-results',
    'no-results-text',
    'results',
    'stats-grid',
    'price-chart',
    'price-tooltip',
    'volume-chart',
    'volume-tooltip',
    'chart-readout',
    'summary-body',
    'export-csv',
    'export-report',
    'page-size',
    'page-prev',
    'page-next',
    'page-info',
    'table-container',
  ];
  for (const id of ids) {
    ui[id] = byId(id);
  }
}

/* ------------------------------------------------------------------ states */

function setLoading(isLoading, text = 'קורא את הקובץ…') {
  ui['loading-text'].textContent = text;
  show(ui.loading, isLoading);
  ui['file-button'].disabled = isLoading;
  ui['load-demo'].disabled = isLoading;
}

function setStatus(message) {
  if (!message) {
    ui['status-message'].textContent = '';
    show(ui['status-message'], false);
    return;
  }
  ui['status-message'].textContent = message;
  show(ui['status-message'], true);
}

function clearValidationReport() {
  clear(ui['validation-report']);
  show(ui['validation-report'], false);
}

/* ------------------------------------------------------------------- import */

async function handleFile(file) {
  clearValidationReport();
  setStatus('');

  if (!file) return;

  // Checked before reading: a 2 GB file should be refused, not loaded into
  // memory first and refused afterwards.
  if (file.size > LIMITS.MAX_BYTES) {
    showBlockedImport(
      {
        issues: [
          {
            kind: 'file-size',
            row: null,
            column: null,
            value: null,
            message: `הקובץ שנבחר במשקל ${formatBytes(
              file.size,
            )}, והמותר הוא עד 5 מ״ב. יש לפצל את הקובץ או לצמצם את טווח התאריכים שבו.`,
          },
        ],
        issueCount: 1,
        truncatedIssues: false,
        warnings: [],
      },
      file.name,
    );
    return;
  }

  setLoading(true);
  try {
    // Yield once so the loading state actually paints before a large parse.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const text = await file.text();
    const result = validateDataset(text, { fileName: file.name, byteSize: file.size });
    if (!result.ok) {
      showBlockedImport(result, file.name);
      return;
    }
    applyDataset(result.dataset, { isDemo: false, warnings: result.warnings });
  } catch (error) {
    showBlockedImport(
      {
        issues: [
          {
            kind: 'read-error',
            row: null,
            column: null,
            value: null,
            message: `לא ניתן לקרוא את הקובץ: ${error instanceof Error ? error.message : 'שגיאה לא מזוהה'}. יש לוודא שהקובץ הוא טקסט בקידוד UTF-8.`,
          },
        ],
        issueCount: 1,
        truncatedIssues: false,
        warnings: [],
      },
      file?.name ?? '',
    );
  } finally {
    setLoading(false);
  }
}

function showBlockedImport(result, fileName) {
  renderValidationReport(ui['validation-report'], result, fileName);
  show(ui['validation-report'], true);
  setStatus('');
  // An earlier successful import is left untouched: a failed new import should
  // not silently wipe the data the user is already looking at.
  ui['validation-report'].focus?.();
}

function loadDemo() {
  clearValidationReport();
  // The demo goes through the very same validator as a user file, so a broken
  // generator shows up as a blocked import instead of as trusted-looking data.
  const csv = generateDemoCsv();
  const result = validateDataset(csv, {
    fileName: DEMO_FILE_NAME,
    byteSize: new TextEncoder().encode(csv).length,
  });
  if (!result.ok) {
    showBlockedImport(result, DEMO_FILE_NAME);
    return;
  }
  applyDataset(result.dataset, { isDemo: true, warnings: result.warnings });
}

function downloadSample() {
  const csv = generateDemoCsv();
  downloadText(safeFileName('sample', todayIso(), 'csv'), csv, 'text/csv');
  setStatus(
    'הורד קובץ CSV לדוגמה עם נתוני הדגמה מומצאים (DEMO_A, DEMO_B, DEMO_C). אפשר לטעון אותו חזרה כדי לבדוק את מסלול הייבוא.',
  );
}

function applyDataset(dataset, { isDemo, warnings }) {
  state.dataset = dataset;
  state.isDemo = isDemo;
  state.selectedSymbol = dataset.symbols[0] ?? null;
  state.sortKey = 'date';
  state.sortDirection = 'asc';
  state.page = 1;
  ui['symbol-search'].value = '';
  resetRangeToSymbol();

  const parts = [
    `נטענו ${formatInteger(dataset.rowCount)} שורות תקפות מהקובץ ${dataset.fileName}`,
    `${formatInteger(dataset.symbols.length)} סמלים`,
    `טווח ${formatDate(dataset.firstDate)}–${formatDate(dataset.lastDate)}`,
  ];
  if (warnings?.length) parts.push(warnings.join(' '));
  setStatus(`${parts.join(' · ')}.`);

  ui['clear-data'].disabled = false;
  render();
}

function clearAll() {
  state.dataset = null;
  state.isDemo = false;
  state.selectedSymbol = null;
  state.from = null;
  state.to = null;
  state.page = 1;
  state.sortKey = 'date';
  state.sortDirection = 'asc';

  ui['file-input'].value = '';
  ui['symbol-search'].value = '';
  ui['date-from'].value = '';
  ui['date-to'].value = '';
  clear(ui['symbol-select']);
  clear(ui['stats-grid']);
  clear(ui['price-chart']);
  clear(ui['volume-chart']);
  clear(ui['summary-body']);
  clear(ui['table-container']);
  clear(ui['source-banner']);
  ui['chart-readout'].textContent = '';
  ui['price-tooltip'].hidden = true;
  ui['volume-tooltip'].hidden = true;
  ui['clear-data'].disabled = true;
  clearValidationReport();
  setStatus('הנתונים נמחקו. לא נשמר דבר בדפדפן.');
  render();
}

/* ------------------------------------------------------------------ filters */

function resetRangeToSymbol() {
  const bounds = state.selectedSymbol
    ? symbolBounds(state.dataset?.rows ?? [], state.selectedSymbol)
    : null;
  state.from = bounds?.firstDate ?? null;
  state.to = bounds?.lastDate ?? null;
  state.page = 1;
}

function syncRangeInputs() {
  const bounds = state.selectedSymbol
    ? symbolBounds(state.dataset?.rows ?? [], state.selectedSymbol)
    : null;
  for (const [key, input] of [
    ['from', ui['date-from']],
    ['to', ui['date-to']],
  ]) {
    if (bounds) {
      input.min = bounds.firstDate;
      input.max = bounds.lastDate;
    } else {
      input.removeAttribute('min');
      input.removeAttribute('max');
    }
    input.value = state[key] ?? '';
  }
}

function renderSymbolOptions() {
  const symbols = state.dataset?.symbols ?? [];
  const matches = searchSymbols(symbols, ui['symbol-search'].value);
  const select = ui['symbol-select'];
  clear(select);

  for (const symbol of matches) {
    // textContent via el(), so a symbol containing markup is shown as text.
    select.append(el('option', { text: symbol, attrs: { value: symbol } }));
  }

  if (matches.length === 0) {
    select.append(el('option', { text: 'אין סמל תואם', attrs: { value: '', disabled: 'disabled' } }));
    ui['symbol-count'].textContent = `אין סמל שתואם לחיפוש. בקובץ יש ${formatInteger(symbols.length)} סמלים.`;
  } else {
    ui['symbol-count'].textContent = `${formatInteger(matches.length)} מתוך ${formatInteger(
      symbols.length,
    )} סמלים תואמים לחיפוש.`;
  }

  if (state.selectedSymbol && matches.includes(state.selectedSymbol)) {
    select.value = state.selectedSymbol;
  } else if (matches.length > 0) {
    select.value = matches[0];
  }
}

/* ------------------------------------------------------------------- render */

/** Phone-width layout: the charts switch to a taller, sparser geometry. */
const compactQuery =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(max-width: 640px)')
    : null;

function isCompactViewport() {
  return Boolean(compactQuery?.matches);
}

function render() {
  const hasData = Boolean(state.dataset);
  show(ui['empty-state'], !hasData);
  show(ui.analysis, hasData);
  if (!hasData) return;

  renderSourceBanner(ui['source-banner'], { dataset: state.dataset, isDemo: state.isDemo });
  renderSymbolOptions();
  syncRangeInputs();

  const range = normalizeRange({ from: state.from, to: state.to });
  if (range.inverted) {
    ui['range-message'].textContent =
      'תאריך ההתחלה מאוחר מתאריך הסיום, ולכן אין תצפיות להצגה. יש להחליף ביניהם או לאפס את הטווח.';
    show(ui['range-message'], true);
  } else {
    show(ui['range-message'], false);
  }

  const symbol = state.selectedSymbol;
  const filtered = range.inverted
    ? []
    : selectRows(state.dataset.rows, { symbol, from: range.from, to: range.to });
  const stats = computeStats(filtered);

  const hasRows = filtered.length > 0;
  show(ui['no-results'], !hasRows);
  show(ui.results, hasRows);

  if (!hasRows) {
    const bounds = symbol ? symbolBounds(state.dataset.rows, symbol) : null;
    ui['no-results-text'].textContent = bounds
      ? `לסמל ${symbol} אין תצפיות בטווח ${formatDate(range.from)} – ${formatDate(range.to)}. ` +
        `הטווח הזמין לסמל זה הוא ${formatDate(bounds.firstDate)} – ${formatDate(bounds.lastDate)}, ובו ${formatInteger(
          bounds.count,
        )} תצפיות. תאריכים חסרים בתוך הטווח אינם שגיאה.`
      : 'לא נבחר סמל, ולכן אין נתונים להצגה.';
    ui['chart-readout'].textContent = '';
    ui['price-tooltip'].hidden = true;
    ui['volume-tooltip'].hidden = true;
    return;
  }

  renderStats(ui['stats-grid'], stats);

  const chartOptions = {
    symbol,
    readout: ui['chart-readout'],
    minDate: stats.minCloseDate,
    maxDate: stats.maxCloseDate,
    compact: isCompactViewport(),
  };
  renderPriceChart(ui['price-chart'], filtered, {
    ...chartOptions,
    tooltip: ui['price-tooltip'],
  });
  renderVolumeChart(ui['volume-chart'], filtered, {
    ...chartOptions,
    tooltip: ui['volume-tooltip'],
  });

  const summary = buildSummary({
    symbol,
    fileName: state.dataset.fileName,
    isDemo: state.isDemo,
    requestedRange: { from: range.from, to: range.to },
    stats,
  });
  renderSummary(ui['summary-body'], summary);

  const sorted = sortRows(filtered, state.sortKey, state.sortDirection);
  const pageData = paginate(sorted, state.page, state.pageSize);
  state.page = pageData.page;
  renderTable(
    ui['table-container'],
    pageData,
    { sortKey: state.sortKey, sortDirection: state.sortDirection, symbol },
    handleSort,
  );

  ui['page-info'].textContent = `עמוד ${pageData.page} מתוך ${pageData.pageCount}`;
  ui['page-prev'].disabled = pageData.page <= 1;
  ui['page-next'].disabled = pageData.page >= pageData.pageCount;

  ui['export-csv'].disabled = false;
  ui['export-report'].disabled = false;
  ui['export-csv'].dataset.rowCount = String(filtered.length);
}

function handleSort(key) {
  if (state.sortKey === key) {
    state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
  } else {
    state.sortKey = key;
    state.sortDirection = key === 'date' ? 'asc' : 'desc';
  }
  state.page = 1;
  render();
}

/* ------------------------------------------------------------------ exports */

function currentSelection() {
  const range = normalizeRange({ from: state.from, to: state.to });
  const rows = range.inverted
    ? []
    : selectRows(state.dataset.rows, {
        symbol: state.selectedSymbol,
        from: range.from,
        to: range.to,
      });
  return { range, rows, stats: computeStats(rows) };
}

function exportCsv() {
  if (!state.dataset || !state.selectedSymbol) return;
  const { rows } = currentSelection();
  const fileName = safeFileName(state.selectedSymbol, todayIso(), 'csv');
  downloadText(fileName, buildCsv(rows), 'text/csv');
  setStatus(`הורדו ${formatInteger(rows.length)} שורות מסוננות לקובץ ${fileName}.`);
}

function exportReport() {
  if (!state.dataset || !state.selectedSymbol) return;
  const { range, rows, stats } = currentSelection();
  const summary = buildSummary({
    symbol: state.selectedSymbol,
    fileName: state.dataset.fileName,
    isDemo: state.isDemo,
    requestedRange: range,
    stats,
  });
  const generatedAt = todayIso();
  const report = buildTextReport({
    symbol: state.selectedSymbol,
    fileName: state.dataset.fileName,
    isDemo: state.isDemo,
    requestedRange: range,
    stats,
    summary,
    generatedAt,
  });
  const fileName = safeFileName(state.selectedSymbol, generatedAt, 'txt');
  downloadText(fileName, report, 'text/plain');
  setStatus(`הורד דוח בעברית עבור ${state.selectedSymbol} (${formatInteger(rows.length)} תצפיות) לקובץ ${fileName}.`);
}

/* -------------------------------------------------------------------- wiring */

function wireEvents() {
  ui['file-button'].addEventListener('click', () => ui['file-input'].click());
  ui['file-input'].addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    handleFile(file);
  });

  const dropzone = ui.dropzone;
  const setDragging = (active) => dropzone.classList.toggle('dragging', active);
  for (const type of ['dragenter', 'dragover']) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      setDragging(true);
    });
  }
  for (const type of ['dragleave', 'dragend']) {
    dropzone.addEventListener(type, () => setDragging(false));
  }
  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer?.files?.[0];
    handleFile(file);
  });
  // Without this, dropping a file anywhere else navigates away from the app.
  for (const type of ['dragover', 'drop']) {
    window.addEventListener(type, (event) => {
      if (!dropzone.contains(event.target)) event.preventDefault();
    });
  }

  ui['load-demo'].addEventListener('click', loadDemo);
  ui['download-sample'].addEventListener('click', downloadSample);
  ui['clear-data'].addEventListener('click', clearAll);

  ui['symbol-search'].addEventListener('input', () => {
    renderSymbolOptions();
    const select = ui['symbol-select'];
    if (select.value && select.value !== state.selectedSymbol) {
      state.selectedSymbol = select.value;
      resetRangeToSymbol();
      render();
    }
  });

  ui['symbol-select'].addEventListener('change', (event) => {
    const value = event.target.value;
    if (!value) return;
    state.selectedSymbol = value;
    resetRangeToSymbol();
    render();
  });

  ui['date-from'].addEventListener('change', (event) => {
    state.from = event.target.value || null;
    state.page = 1;
    render();
  });
  ui['date-to'].addEventListener('change', (event) => {
    state.to = event.target.value || null;
    state.page = 1;
    render();
  });
  ui['reset-range'].addEventListener('click', () => {
    resetRangeToSymbol();
    render();
  });

  ui['page-size'].addEventListener('change', (event) => {
    state.pageSize = Number(event.target.value) || 25;
    state.page = 1;
    render();
  });
  ui['page-prev'].addEventListener('click', () => {
    state.page = Math.max(1, state.page - 1);
    render();
  });
  ui['page-next'].addEventListener('click', () => {
    state.page += 1;
    render();
  });

  ui['export-csv'].addEventListener('click', exportCsv);
  ui['export-report'].addEventListener('click', exportReport);

  // Crossing the phone breakpoint changes the chart geometry, so redraw.
  compactQuery?.addEventListener('change', () => {
    if (state.dataset) render();
  });
}

function init() {
  cacheElements();
  wireEvents();
  render();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

export { state, init };
