/**
 * Static panels: the statistics grid, the validation report, the source banner
 * and the automatic summary. All of them render text nodes only.
 */

import { clear, el, num } from './dom.js';
import {
  formatBytes,
  formatDate,
  formatInteger,
  formatPercent,
  formatPrice,
  formatVolume,
} from '../lib/format.js';
import { STAT_EXPLANATIONS } from '../lib/stats.js';
import { LIMITS } from '../lib/validate.js';

/**
 * One statistic: label, value, and a short Hebrew explanation of what it means.
 * @param {string} label
 * @param {(Node|string)[]} valueParts
 * @param {string} note
 * @param {string} [extraClass]
 */
function statCard(label, valueParts, note, extraClass = '') {
  const card = el('div', { class: extraClass ? `stat-card ${extraClass}` : 'stat-card' });
  card.append(el('div', { class: 'stat-label', text: label }));
  const value = el('div', { class: 'stat-value' });
  for (const part of valueParts) {
    value.append(typeof part === 'string' ? document.createTextNode(part) : part);
  }
  card.append(value);
  card.append(el('p', { class: 'stat-note', text: note }));
  return card;
}

/**
 * @param {HTMLElement} container
 * @param {ReturnType<import('../lib/stats.js').computeStats>} stats
 */
export function renderStats(container, stats) {
  clear(container);

  container.append(
    statCard('מספר תצפיות', [num(formatInteger(stats.count))], STAT_EXPLANATIONS.count),
  );

  container.append(
    statCard(
      'תצפית ראשונה',
      [num(formatDate(stats.firstDate)), ' · ', num(formatPrice(stats.firstClose))],
      `${STAT_EXPLANATIONS.firstDate} ${STAT_EXPLANATIONS.firstClose}`,
    ),
  );

  container.append(
    statCard(
      'תצפית אחרונה',
      [num(formatDate(stats.lastDate)), ' · ', num(formatPrice(stats.lastClose))],
      `${STAT_EXPLANATIONS.lastDate} ${STAT_EXPLANATIONS.lastClose}`,
    ),
  );

  // Direction is carried by a word and a glyph as well as by colour, so it still
  // reads correctly in monochrome, in forced-colours mode and for colour-blind
  // readers.
  const percent = stats.percentChange;
  const direction = percent === null ? 'neutral' : percent > 0 ? 'up' : percent < 0 ? 'down' : 'neutral';
  const directionWord =
    direction === 'up' ? 'עלייה' : direction === 'down' ? 'ירידה' : 'ללא שינוי';
  const glyph = direction === 'up' ? '▲' : direction === 'down' ? '▼' : '■';
  const changeCard = statCard(
    'שינוי באחוזים בתקופה',
    [
      el('span', { class: 'delta-glyph', text: glyph, attrs: { 'aria-hidden': 'true' } }),
      num(formatPercent(percent)),
      el('span', { class: 'delta-word', text: directionWord }),
    ],
    STAT_EXPLANATIONS.percentChange,
    `stat-change delta-${direction}`,
  );
  container.append(changeCard);

  container.append(
    statCard(
      'סגירה נמוכה בטווח',
      [num(formatPrice(stats.minClose)), ' · ', num(formatDate(stats.minCloseDate))],
      STAT_EXPLANATIONS.minClose,
    ),
  );

  container.append(
    statCard(
      'סגירה גבוהה בטווח',
      [num(formatPrice(stats.maxClose)), ' · ', num(formatDate(stats.maxCloseDate))],
      STAT_EXPLANATIONS.maxClose,
    ),
  );

  container.append(
    statCard(
      'מחזור ממוצע לתצפית',
      [num(formatVolume(stats.averageVolume))],
      STAT_EXPLANATIONS.averageVolume,
    ),
  );
}

/**
 * The validation report. Row numbers refer to lines in the source file, so the
 * user can open the file and go straight to the problem.
 *
 * @param {HTMLElement} container
 * @param {{issues: any[], issueCount: number, truncatedIssues: boolean, warnings: string[]}} result
 * @param {string} fileName
 */
export function renderValidationReport(container, result, fileName) {
  clear(container);

  const heading = el('h3', {
    text: `הייבוא נחסם: נמצאו ${formatInteger(result.issueCount)} בעיות בקובץ`,
  });
  container.append(heading);
  container.append(
    el('p', {
      class: 'report-intro',
      text:
        `הקובץ ${fileName || ''} לא נטען. הכלי אינו מדלג על שורות שגויות ואינו ממלא ערכים חסרים, ` +
        'כדי שהחישובים לא יתבססו על נתונים שהומצאו. יש לתקן את השורות הבאות ולנסות שוב.',
    }),
  );

  const list = el('ul', { class: 'issue-list' });
  for (const issue of result.issues) {
    const item = el('li');
    const location = [];
    if (issue.row !== null) location.push(`שורה ${issue.row}`);
    if (issue.column) location.push(`עמודה ${issue.column}`);
    if (location.length > 0) {
      item.append(el('span', { class: 'issue-where', text: location.join(' · ') }));
    }
    item.append(el('span', { class: 'issue-message', text: issue.message }));
    if (issue.value !== null && issue.value !== '') {
      const valueWrap = el('span', { class: 'issue-value' });
      valueWrap.append(document.createTextNode('הערך שנמצא: '));
      valueWrap.append(num(issue.value, 'issue-raw'));
      item.append(valueWrap);
    }
    list.append(item);
  }
  container.append(list);

  if (result.truncatedIssues) {
    container.append(
      el('p', {
        class: 'report-more',
        text: `מוצגות ${LIMITS.MAX_ISSUES_REPORTED} הבעיות הראשונות בלבד. ייתכן שיש בעיות נוספות בהמשך הקובץ.`,
      }),
    );
  }

  if (result.warnings.length > 0) {
    const warnList = el('ul', { class: 'issue-list warnings' });
    for (const warning of result.warnings) {
      warnList.append(el('li', { children: [el('span', { class: 'issue-message', text: warning })] }));
    }
    container.append(el('h4', { text: 'הערות נוספות' }));
    container.append(warnList);
  }
}

/**
 * The source banner: filename, size, row count, available range, and the
 * provenance statement.
 *
 * @param {HTMLElement} container
 * @param {{dataset: any, isDemo: boolean}} state
 */
export function renderSourceBanner(container, { dataset, isDemo }) {
  clear(container);

  const rows = [
    ['קובץ מקור', dataset.fileName || 'לא צוין'],
    ['גודל', formatBytes(dataset.byteSize)],
    ['שורות תקפות', formatInteger(dataset.rowCount)],
    ['סמלים בקובץ', formatInteger(dataset.symbols.length)],
    ['טווח תאריכים זמין', `${formatDate(dataset.firstDate)} – ${formatDate(dataset.lastDate)}`],
  ];

  const list = el('dl', { class: 'source-list' });
  for (const [label, value] of rows) {
    list.append(el('dt', { text: label }));
    list.append(el('dd', { children: [num(value)] }));
  }
  container.append(list);

  const provenance = el('p', { class: 'provenance' });
  provenance.textContent = isDemo
    ? 'אלה נתוני הדגמה מומצאים שנוצרו בתוך הכלי (DEMO_A, DEMO_B, DEMO_C). הם אינם מתייחסים לחברה או לנייר ערך אמיתיים ואינם נתוני שוק.'
    : 'אלה רשומות היסטוריות שהמשתמש טען. הן אינן נתוני שוק מאומתים, ולא נבדקו מול שום מקור חיצוני.';
  container.append(provenance);

  if (dataset.wasReordered) {
    container.append(
      el('p', {
        class: 'notice-sorted',
        text: 'השורות בקובץ לא היו בסדר כרונולוגי ולכן סודרו מחדש לפי תאריך לצורך התצוגה והחישוב. הקובץ המקורי לא שונה.',
      }),
    );
  }
}

/**
 * @param {HTMLElement} container
 * @param {{title: string, paragraphs: string[], limitations: string[]}} summary
 */
export function renderSummary(container, summary) {
  clear(container);
  for (const paragraph of summary.paragraphs) {
    container.append(el('p', { text: paragraph }));
  }
  const details = el('details', { class: 'limitations' });
  details.append(el('summary', { text: 'מגבלות הנתונים' }));
  const list = el('ul');
  for (const item of summary.limitations) {
    list.append(el('li', { text: item }));
  }
  details.append(list);
  container.append(details);
}
