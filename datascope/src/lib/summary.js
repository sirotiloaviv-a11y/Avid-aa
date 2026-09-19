/**
 * Hebrew automatic summary - local text templates only.
 *
 * There is no AI model, no network call and no external service behind this
 * module. It fills sentences from numbers that stats.js already computed, which
 * is exactly why the UI can label the result "סיכום אוטומטי" without claiming
 * anything about how it was produced.
 *
 * Kept separate from the UI and from the statistics so a richer generator can
 * replace `buildSummary()` later without touching either. The output shape is
 * the contract: a list of plain-text paragraphs plus a list of limitations.
 * Returning text (never markup) is also what keeps imported symbol names from
 * ever being interpreted as HTML.
 */

import { formatDate, formatPercent, formatPrice, formatVolume, formatInteger } from './format.js';

export const SUMMARY_GENERATOR = Object.freeze({
  kind: 'local-template',
  version: 1,
  usesAiModel: false,
});

/**
 * Wording for the direction of the move. Deliberately descriptive - the summary
 * reports what the numbers say and never suggests an action.
 * @param {number|null} percent
 */
function describeDirection(percent) {
  if (percent === null) return 'ללא שינוי מחושב';
  if (percent > 0) return 'עלייה';
  if (percent < 0) return 'ירידה';
  return 'ללא שינוי';
}

/**
 * @param {object} input
 * @param {string} input.symbol
 * @param {string} input.fileName
 * @param {boolean} input.isDemo
 * @param {{from: string|null, to: string|null}} input.requestedRange
 * @param {ReturnType<import('./stats.js').computeStats>} input.stats
 * @returns {{title: string, generator: object, paragraphs: string[], limitations: string[]}}
 */
export function buildSummary({ symbol, fileName, isDemo, requestedRange, stats }) {
  const title = 'סיכום אוטומטי';
  const limitations = buildLimitations({ isDemo });

  if (!symbol) {
    return {
      title,
      generator: SUMMARY_GENERATOR,
      paragraphs: ['לא נבחר סמל. יש לבחור סמל כדי לקבל סיכום.'],
      limitations,
    };
  }

  if (stats.count === 0) {
    return {
      title,
      generator: SUMMARY_GENERATOR,
      paragraphs: [
        `עבור הסמל ${symbol} אין תצפיות בטווח התאריכים שנבחר` +
          rangeSuffix(requestedRange) +
          '. אין זו שגיאה: ייתכן שהקובץ אינו מכיל רשומות בטווח הזה.',
      ],
      limitations,
    };
  }

  const paragraphs = [];

  paragraphs.push(
    `הסמל ${symbol} נבדק על פני ${formatInteger(stats.count)} תצפיות ` +
      `מהקובץ ${fileName || 'שנטען'}, מ־${formatDate(stats.firstDate)} עד ${formatDate(stats.lastDate)}. ` +
      'התאריכים הם התצפית הראשונה והאחרונה שקיימות בנתונים בטווח שנבחר, ולא בהכרח קצות הטווח עצמו.',
  );

  if (stats.singleObservation) {
    paragraphs.push(
      `בטווח קיימת תצפית אחת בלבד, במחיר סגירה ${formatPrice(stats.lastClose)}. ` +
        'עם תצפית אחת אין מה להשוות, ולכן השינוי באחוזים מוצג כאפס ואין משמעות למינימום, למקסימום או למגמה.',
    );
  } else {
    paragraphs.push(
      `מחיר הסגירה נע מ־${formatPrice(stats.firstClose)} בתצפית הראשונה ל־${formatPrice(stats.lastClose)} בתצפית האחרונה: ` +
        `${describeDirection(stats.percentChange)} של ${formatPercent(stats.percentChange)} על פני התקופה. ` +
        'החישוב הוא 100 × (סגירה אחרונה / סגירה ראשונה − 1) בין שתי התצפיות הללו בלבד, ואינו מתאר את הדרך ביניהן.',
    );
    paragraphs.push(
      `הסגירה הנמוכה ביותר בטווח הייתה ${formatPrice(stats.minClose)} ב־${formatDate(stats.minCloseDate)}, ` +
        `והגבוהה ביותר ${formatPrice(stats.maxClose)} ב־${formatDate(stats.maxCloseDate)}. ` +
        `המחזור הממוצע לתצפית הוא ${formatVolume(stats.averageVolume)}.`,
    );
  }

  paragraphs.push(
    'הנתונים מתארים מה נרשם בקובץ. הם אינם מסבירים מדוע המחיר זז: ' +
      'מחירים לבדם אינם מכילים את הסיבה, והכלי אינו מנסה לשחזר אותה.',
  );

  return { title, generator: SUMMARY_GENERATOR, paragraphs, limitations };
}

function rangeSuffix(range) {
  if (!range) return '';
  const { from, to } = range;
  if (from && to) return ` (${formatDate(from)}–${formatDate(to)})`;
  if (from) return ` (מ־${formatDate(from)})`;
  if (to) return ` (עד ${formatDate(to)})`;
  return '';
}

/**
 * The limitations that apply to every summary and to the exported report.
 * @param {{isDemo?: boolean}} [options]
 * @returns {string[]}
 */
export function buildLimitations({ isDemo = false } = {}) {
  const items = [
    'הנתונים הם רשומות היסטוריות שהמשתמש טען. הם אינם נתוני שוק מאומתים ולא נבדקו מול מקור חיצוני.',
    'התוצאות תלויות בשאלה אם המחירים בקובץ מתואמים לפיצולי מניות ולדיבידנדים. הכלי אינו מבצע התאמות כאלה ואינו יכול לזהות אם בוצעו.',
    'הקובץ אינו מציין מטבע, ואין הנחה שכל הסמלים נקובים באותו מטבע. אין להשוות מחירים בין סמלים ללא מידע נוסף.',
    'תאריכים שאינם מופיעים בקובץ (סופי שבוע, חגים, ימים חסרים) אינם נחשבים שגיאה ואינם מושלמים או מוערכים.',
    'חישובי המחזור הממוצע והשינוי באחוזים מתייחסים רק לתצפיות הקיימות בטווח שנבחר.',
    'זהו כלי לימודי לניתוח נתונים היסטוריים. אין בו המלצות, אין בו תחזיות ואין בו נתוני זמן אמת.',
  ];
  if (isDemo) {
    items.unshift(
      'נתוני ההדגמה (DEMO_A, DEMO_B, DEMO_C) הם נתונים מומצאים שנוצרו באופן דטרמיניסטי לצורך הדגמה בלבד. הם אינם מתייחסים לחברה, לנייר ערך או לשוק אמיתיים.',
    );
  }
  return items;
}
