/**
 * Descriptive statistics.
 *
 * Every number here is produced by plain arithmetic over the rows handed in -
 * no sampling, no smoothing, no model. Intermediate values are never rounded;
 * rounding belongs to format.js, at the moment of display.
 *
 * Nothing in this module tries to explain *why* a price moved. Prices alone do
 * not carry that information, and the UI copy says so.
 */

/**
 * @typedef {object} Observation
 * @property {string} date YYYY-MM-DD
 * @property {string} symbol
 * @property {number} close
 * @property {number} volume
 */

/**
 * Percentage change between two closes: 100 × (last / first − 1).
 *
 * The expression is evaluated exactly as written, with no intermediate rounding,
 * so the result carries normal binary floating-point error: 100 and 110 give
 * 10.000000000000009, not 10. Rounding it here would be rounding an
 * intermediate value; the display layer rounds instead, and shows "+10.00%".
 *
 * @param {number} firstClose Must be > 0 (guaranteed by validation).
 * @param {number} lastClose
 * @returns {number|null} null when the base is unusable.
 */
export function percentChange(firstClose, lastClose) {
  if (!Number.isFinite(firstClose) || !Number.isFinite(lastClose)) return null;
  if (firstClose <= 0) return null;
  return 100 * (lastClose / firstClose - 1);
}

/**
 * @param {Observation[]} rows Already filtered to one symbol and sorted by date.
 * @returns {{
 *   count: number, firstDate: string|null, lastDate: string|null,
 *   firstClose: number|null, lastClose: number|null, percentChange: number|null,
 *   minClose: number|null, minCloseDate: string|null,
 *   maxClose: number|null, maxCloseDate: string|null,
 *   averageVolume: number|null, totalVolume: number,
 *   singleObservation: boolean
 * }}
 */
export function computeStats(rows) {
  const empty = {
    count: 0,
    firstDate: null,
    lastDate: null,
    firstClose: null,
    lastClose: null,
    percentChange: null,
    minClose: null,
    minCloseDate: null,
    maxClose: null,
    maxCloseDate: null,
    averageVolume: null,
    totalVolume: 0,
    singleObservation: false,
  };
  if (!Array.isArray(rows) || rows.length === 0) return empty;

  const first = rows[0];
  const last = rows[rows.length - 1];

  let minClose = first.close;
  let minCloseDate = first.date;
  let maxClose = first.close;
  let maxCloseDate = first.date;
  let totalVolume = 0;

  for (const row of rows) {
    if (row.close < minClose) {
      minClose = row.close;
      minCloseDate = row.date;
    }
    if (row.close > maxClose) {
      maxClose = row.close;
      maxCloseDate = row.date;
    }
    totalVolume += row.volume;
  }

  return {
    count: rows.length,
    firstDate: first.date,
    lastDate: last.date,
    firstClose: first.close,
    lastClose: last.close,
    percentChange: percentChange(first.close, last.close),
    minClose,
    minCloseDate,
    maxClose,
    maxCloseDate,
    averageVolume: totalVolume / rows.length,
    totalVolume,
    singleObservation: rows.length === 1,
  };
}

/**
 * Short Hebrew explanations, keyed by statistic. Kept next to the computation so
 * the wording and the maths cannot drift apart.
 */
export const STAT_EXPLANATIONS = Object.freeze({
  count: 'מספר התצפיות (שורות) בקובץ שנכללות בסמל ובטווח התאריכים שנבחרו.',
  firstDate: 'תאריך התצפית הראשונה שקיימת בנתונים בתוך הטווח — לא בהכרח תחילת הטווח שבחרת.',
  lastDate: 'תאריך התצפית האחרונה שקיימת בנתונים בתוך הטווח — לא בהכרח סוף הטווח שבחרת.',
  firstClose: 'מחיר הסגירה בתצפית הראשונה בטווח, כפי שהופיע בקובץ.',
  lastClose: 'מחיר הסגירה בתצפית האחרונה בטווח, כפי שהופיע בקובץ.',
  percentChange:
    'השינוי באחוזים בין הסגירה הראשונה לאחרונה בטווח, לפי הנוסחה 100 × (סגירה אחרונה / סגירה ראשונה − 1). זו אינה תשואה כוללת: היא אינה מביאה בחשבון דיבידנדים, פיצולים או עמלות.',
  minClose: 'מחיר הסגירה הנמוך ביותר בטווח, והתאריך שבו נרשם.',
  maxClose: 'מחיר הסגירה הגבוה ביותר בטווח, והתאריך שבו נרשם.',
  averageVolume:
    'ממוצע חשבוני של המחזור על פני התצפיות בטווח: סכום המחזורים חלקי מספר התצפיות. ימים שאינם מופיעים בקובץ אינם נספרים.',
});
