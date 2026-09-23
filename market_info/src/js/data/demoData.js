// Demo dataset. Every asset, price, headline and event in this file is
// fictional. Values are generated from a fixed seed so every screen sees the
// same numbers; only the time anchor ("now") moves.

export const DEMO_SEED = 20260923;
const DAY_MS = 24 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

export const ALERT_TYPES = ['price', 'volume', 'news'];
export const PRICE_ALERT_THRESHOLD_PCT = 4;
export const VOLUME_ALERT_MULTIPLE = 2;
const ALERT_LOOKBACK_BARS = 10;

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// `shock` pins a deliberate move on a given bar so that the demo alerts are
// stable and explainable: barsAgo 0 is the latest bar.
export const ASSETS = [
  { symbol: 'ORLN', name: 'אורלן מערכות', type: 'stock', sector: 'טכנולוגיה', currency: 'USD',
    basePrice: 142.3, volatility: 0.018, baseVolume: 4_200_000,
    shock: { barsAgo: 1, move: 0.058, volumeMultiple: 2.9 } },
  { symbol: 'KNRT', name: 'כנרת אנרגיה', type: 'stock', sector: 'אנרגיה', currency: 'USD',
    basePrice: 58.7, volatility: 0.015, baseVolume: 2_600_000,
    shock: { barsAgo: 3, move: -0.047, volumeMultiple: 1.6 } },
  { symbol: 'MGDL', name: 'מגדלור ביומד', type: 'stock', sector: 'בריאות', currency: 'USD',
    basePrice: 23.15, volatility: 0.026, baseVolume: 6_900_000,
    shock: { barsAgo: 0, move: 0.012, volumeMultiple: 3.1 } },
  { symbol: 'TVLA', name: 'תבל לוגיסטיקה', type: 'stock', sector: 'תעשייה', currency: 'USD',
    basePrice: 87.4, volatility: 0.012, baseVolume: 1_300_000 },
  { symbol: 'SHKD', name: 'שקד מזון', type: 'stock', sector: 'צריכה', currency: 'USD',
    basePrice: 34.9, volatility: 0.01, baseVolume: 950_000 },
  { symbol: 'ARBL', name: 'ארבל פיננסים', type: 'stock', sector: 'פיננסים', currency: 'USD',
    basePrice: 112.6, volatility: 0.014, baseVolume: 2_100_000,
    shock: { barsAgo: 5, move: -0.041, volumeMultiple: 2.2 } },
  { symbol: 'NOVX', name: 'נובה', type: 'crypto', sector: 'פלטפורמת חוזים', currency: 'USD',
    basePrice: 1840, volatility: 0.032, baseVolume: 310_000_000,
    shock: { barsAgo: 2, move: 0.072, volumeMultiple: 2.6 } },
  { symbol: 'LMNC', name: 'לומן', type: 'crypto', sector: 'תשלומים', currency: 'USD',
    basePrice: 0.8421, volatility: 0.038, baseVolume: 95_000_000 },
  { symbol: 'ZFRT', name: 'צפיר', type: 'crypto', sector: 'אחסון מבוזר', currency: 'USD',
    basePrice: 12.37, volatility: 0.041, baseVolume: 42_000_000,
    shock: { barsAgo: 0, move: -0.063, volumeMultiple: 2.4 } },
  { symbol: 'TKLT', name: 'טכלת', type: 'crypto', sector: 'תשתית רשת', currency: 'USD',
    basePrice: 64.05, volatility: 0.029, baseVolume: 58_000_000 },
];

export const NEWS_CATEGORIES = ['דוחות כספיים', 'מאקרו', 'רגולציה', 'מוצרים וטכנולוגיה', 'מסחר ושוק', 'רשת ובלוקצ׳יין'];

// hoursAgo is relative to the dataset anchor; `alert: true` makes the item
// raise a "new article" information alert.
const NEWS_TEMPLATES = [
  { id: 'n01', hoursAgo: 1.5, symbols: ['MGDL'], category: 'מוצרים וטכנולוגיה', alert: true,
    title: 'מגדלור ביומד מסרה כי השלימה שלב גיוס מטופלים בניסוי קליני',
    summary: 'לפי הודעת החברה הבדיונית, הושלם גיוס המשתתפים לשלב השני של הניסוי. תוצאות ראשוניות צפויות, לדבריה, ברבעון הבא.' },
  { id: 'n02', hoursAgo: 3, symbols: ['ZFRT'], category: 'רשת ובלוקצ׳יין', alert: true,
    title: 'רשת צפיר דיווחה על האטה זמנית באישור עסקאות',
    summary: 'צוות הפיתוח של הרשת הבדיונית פרסם כי זמני האישור התארכו במשך כשעתיים וכי התקלה אותרה. לא דווח על אובדן נתונים.' },
  { id: 'n03', hoursAgo: 5, symbols: [], category: 'מאקרו', alert: false,
    title: 'מדד המחירים לצרכן במדינת ההדגמה עלה ב-0.3% בחודש האחרון',
    summary: 'על פי פרסום הלשכה הבדיונית לסטטיסטיקה, העלייה נבעה בעיקר מסעיפי הדיור והתחבורה.' },
  { id: 'n04', hoursAgo: 8, symbols: ['ORLN'], category: 'דוחות כספיים', alert: true,
    title: 'אורלן מערכות: פרטים מתוך הדוח הרבעוני — הכנסות של 1.84 מיליארד דולר',
    summary: 'החברה הבדיונית דיווחה על גידול של 12% בהכנסות לעומת הרבעון המקביל. הדוח כולל עדכון לתחזית השנתית.' },
  { id: 'n05', hoursAgo: 11, symbols: ['NOVX'], category: 'רשת ובלוקצ׳יין', alert: false,
    title: 'רשת נובה הודיעה על מועד לעדכון פרוטוקול',
    summary: 'לפי הודעת המפתחים, העדכון יתבצע בעוד כשבועיים ויכלול שינויים במנגנון העמלות.' },
  { id: 'n06', hoursAgo: 14, symbols: ['KNRT'], category: 'מסחר ושוק', alert: false,
    title: 'כנרת אנרגיה: עדכון על תחזוקה מתוכננת במתקן ייצור',
    summary: 'החברה הבדיונית מסרה כי אחד המתקנים יושבת לתחזוקה של עשרה ימים, כמתוכנן מראש.' },
  { id: 'n07', hoursAgo: 19, symbols: ['ARBL'], category: 'רגולציה', alert: false,
    title: 'הרגולטור הבדיוני פרסם טיוטת הנחיות להון עצמי של גופים פיננסיים',
    summary: 'הטיוטה פתוחה להערות הציבור במשך 30 יום. ארבל פיננסים ציינה כי היא בוחנת את המסמך.' },
  { id: 'n08', hoursAgo: 23, symbols: ['LMNC'], category: 'מוצרים וטכנולוגיה', alert: false,
    title: 'לומן השיקה ממשק תכנות חדש לסוחרים',
    summary: 'לפי הודעת הפרויקט הבדיוני, הממשק מיועד לעיבוד תשלומים בכמות גבוהה ונמצא כעת בגרסת ניסיון.' },
  { id: 'n09', hoursAgo: 27, symbols: ['TVLA'], category: 'דוחות כספיים', alert: false,
    title: 'תבל לוגיסטיקה: נפח המשלוחים ברבעון עלה ב-4%',
    summary: 'בנתונים תפעוליים שפרסמה החברה הבדיונית נמסר כי הגידול נרשם בעיקר בקווים הבינלאומיים.' },
  { id: 'n10', hoursAgo: 31, symbols: [], category: 'מאקרו', alert: false,
    title: 'הבנק המרכזי של מדינת ההדגמה פרסם פרוטוקול מהדיון האחרון',
    summary: 'בפרוטוקול צוין כי הוועדה דנה בנתוני התעסוקה ובקצב האינפלציה. החלטת הריבית הבאה מתוכננת בשבוע הבא.' },
  { id: 'n11', hoursAgo: 36, symbols: ['SHKD'], category: 'מוצרים וטכנולוגיה', alert: false,
    title: 'שקד מזון הודיעה על פתיחת קו ייצור נוסף',
    summary: 'לפי החברה הבדיונית, הקו החדש יגדיל את כושר הייצור בכ-8% ויופעל בהדרגה.' },
  { id: 'n12', hoursAgo: 42, symbols: ['NOVX', 'TKLT'], category: 'רגולציה', alert: false,
    title: 'פורסם נוסח מעודכן לכללי דיווח על נכסים דיגיטליים במדינת ההדגמה',
    summary: 'הנוסח הבדיוני מגדיר חובות דיווח חדשות לפלטפורמות מסחר. מועד הכניסה לתוקף טרם נקבע.' },
  { id: 'n13', hoursAgo: 49, symbols: ['KNRT'], category: 'דוחות כספיים', alert: false,
    title: 'כנרת אנרגיה עדכנה את תחזית ההפקה השנתית',
    summary: 'החברה הבדיונית הורידה את טווח התחזית בכ-3%, בעיקר בשל עיכוב בחיבור מתקן חדש.' },
  { id: 'n14', hoursAgo: 55, symbols: ['TKLT'], category: 'רשת ובלוקצ׳יין', alert: false,
    title: 'טכלת: מספר הצמתים הפעילים חצה את רף ה-10,000',
    summary: 'על פי נתוני הרשת הבדיונית, מספר הצמתים גדל בכ-15% מתחילת הרבעון.' },
  { id: 'n15', hoursAgo: 63, symbols: ['ORLN'], category: 'מוצרים וטכנולוגיה', alert: false,
    title: 'אורלן מערכות הציגה פלטפורמת ענן לעסקים קטנים',
    summary: 'המוצר הבדיוני יושק תחילה בשלושה שווקים. החברה לא מסרה נתונים על היקף ההכנסות הצפוי.' },
  { id: 'n16', hoursAgo: 70, symbols: [], category: 'מסחר ושוק', alert: false,
    title: 'בורסת ההדגמה: שעות המסחר ישתנו לרגל חג',
    summary: 'המסחר יתקיים בשעות מקוצרות ביום שני הבא. לוח האירועים עודכן בהתאם.' },
  { id: 'n17', hoursAgo: 78, symbols: ['MGDL'], category: 'רגולציה', alert: false,
    title: 'מגדלור ביומד קיבלה אישור לקיים ניסוי במדינה נוספת',
    summary: 'לפי הודעת החברה הבדיונית, האישור מאפשר הרחבה של אתרי הניסוי הקליני.' },
  { id: 'n18', hoursAgo: 90, symbols: ['ARBL'], category: 'דוחות כספיים', alert: false,
    title: 'ארבל פיננסים: הכנסות הריבית נטו ירדו ב-2% ברבעון',
    summary: 'בדוח הבדיוני נמסר כי הירידה משקפת שינוי בתמהיל הפיקדונות.' },
];

// dayOffset is counted in whole UTC days from the anchor date.
const EVENT_TEMPLATES = [
  { id: 'e01', dayOffset: 0, hourUTC: 12, minute: 30, type: 'נתוני מאקרו', symbols: [],
    title: 'פרסום נתוני תעסוקה חודשיים (מדינת ההדגמה)', description: 'פרסום סטטיסטי מתוזמן של הלשכה הבדיונית.' },
  { id: 'e02', dayOffset: 0, hourUTC: 20, minute: 5, type: 'דוח חברה', symbols: ['SHKD'],
    title: 'שקד מזון — דוח רבעוני', description: 'פרסום דוח לאחר סיום המסחר, לפי לוח החברה הבדיוני.' },
  { id: 'e03', dayOffset: 1, hourUTC: 13, minute: 0, type: 'נתוני מאקרו', symbols: [],
    title: 'מדד מנהלי הרכש (מדינת ההדגמה)', description: 'סקר חודשי של מנהלי רכש בתעשייה.' },
  { id: 'e04', dayOffset: 1, hourUTC: 21, minute: 0, type: 'דוח חברה', symbols: ['TVLA'],
    title: 'תבל לוגיסטיקה — שיחת ועידה למשקיעים', description: 'שיחה שבה מוצגים נתוני הרבעון.' },
  { id: 'e05', dayOffset: 2, hourUTC: 9, minute: 0, type: 'אירוע רשת', symbols: ['TKLT'],
    title: 'טכלת — חלון תחזוקה מתוכנן', description: 'תחזוקה של שרתי התשתית של הרשת הבדיונית.' },
  { id: 'e06', dayOffset: 3, hourUTC: 18, minute: 0, type: 'החלטת ריבית', symbols: [],
    title: 'החלטת ריבית — הבנק המרכזי של מדינת ההדגמה', description: 'הודעה על החלטת הריבית ופרסום הודעה לעיתונות.' },
  { id: 'e07', dayOffset: 4, hourUTC: 11, minute: 0, type: 'אספה כללית', symbols: ['ARBL'],
    title: 'ארבל פיננסים — אספת בעלי מניות', description: 'אספה כללית שנתית, לפי הזימון הבדיוני.' },
  { id: 'e08', dayOffset: 5, hourUTC: 20, minute: 10, type: 'דוח חברה', symbols: ['ORLN'],
    title: 'אורלן מערכות — יום משקיעים', description: 'מצגת אסטרטגית של ההנהלה.' },
  { id: 'e09', dayOffset: 6, hourUTC: 12, minute: 30, type: 'נתוני מאקרו', symbols: [],
    title: 'מדד המחירים לצרכן (מדינת ההדגמה)', description: 'פרסום חודשי של מדד המחירים.' },
  { id: 'e10', dayOffset: 7, hourUTC: 15, minute: 0, type: 'אירוע רשת', symbols: ['NOVX'],
    title: 'נובה — עדכון פרוטוקול', description: 'עדכון שהוכרז על ידי מפתחי הרשת הבדיונית.' },
  { id: 'e11', dayOffset: 8, hourUTC: 20, minute: 5, type: 'דוח חברה', symbols: ['KNRT'],
    title: 'כנרת אנרגיה — דוח רבעוני', description: 'פרסום דוח לאחר סיום המסחר.' },
  { id: 'e12', dayOffset: 9, hourUTC: 12, minute: 30, type: 'נתוני מאקרו', symbols: [],
    title: 'מכירות קמעונאיות (מדינת ההדגמה)', description: 'פרסום חודשי של נתוני הצריכה.' },
  { id: 'e13', dayOffset: 10, hourUTC: 20, minute: 5, type: 'דוח חברה', symbols: ['MGDL'],
    title: 'מגדלור ביומד — דוח רבעוני', description: 'פרסום דוח ועדכון על הניסויים הקליניים.' },
  { id: 'e14', dayOffset: 11, hourUTC: 8, minute: 0, type: 'אירוע רשת', symbols: ['LMNC'],
    title: 'לומן — סיום תקופת ניסיון לממשק החדש', description: 'מעבר הממשק לגרסה יציבה, לפי הודעת הפרויקט הבדיוני.' },
  { id: 'e15', dayOffset: 12, hourUTC: 13, minute: 0, type: 'נתוני מאקרו', symbols: [],
    title: 'תוצר מקומי גולמי — אומדן ראשון (מדינת ההדגמה)', description: 'פרסום רבעוני.' },
  { id: 'e16', dayOffset: 13, hourUTC: 20, minute: 5, type: 'דוח חברה', symbols: ['ARBL'],
    title: 'ארבל פיננסים — דוח רבעוני', description: 'פרסום דוח לאחר סיום המסחר.' },
  { id: 'e17', dayOffset: -1, hourUTC: 14, minute: 0, type: 'נתוני מאקרו', symbols: [],
    title: 'נתוני סחר חוץ (מדינת ההדגמה)', description: 'פרסום חודשי.' },
  { id: 'e18', dayOffset: -2, hourUTC: 20, minute: 5, type: 'דוח חברה', symbols: ['ORLN'],
    title: 'אורלן מערכות — דוח רבעוני', description: 'פרסום דוח לאחר סיום המסחר.' },
];

export const EVENT_TYPES = [...new Set(EVENT_TEMPLATES.map((e) => e.type))];

function isWeekend(date) {
  const d = date.getUTCDay();
  return d === 0 || d === 6;
}

// Stocks close at 20:00 UTC on weekdays; crypto bars close at 00:00 UTC daily.
function barTimes(asset, count, now) {
  const times = [];
  const cursor = new Date(now);
  if (asset.type === 'stock') {
    cursor.setUTCHours(20, 0, 0, 0);
  } else {
    cursor.setUTCHours(0, 0, 0, 0);
  }
  if (cursor.getTime() > now.getTime()) cursor.setTime(cursor.getTime() - DAY_MS);
  while (times.length < count) {
    if (asset.type === 'crypto' || !isWeekend(cursor)) times.push(cursor.getTime());
    cursor.setTime(cursor.getTime() - DAY_MS);
  }
  return times.reverse();
}

export function generateHistory(asset, count, now) {
  const rng = mulberry32(DEMO_SEED ^ hashString(asset.symbol));
  const times = barTimes(asset, count, now);
  const bars = [];
  let price = asset.basePrice * (0.85 + rng() * 0.2);
  for (let i = 0; i < count; i++) {
    const barsAgo = count - 1 - i;
    const open = price;
    let move = (rng() - 0.49) * 2 * asset.volatility;
    let volumeMultiple = 0.7 + rng() * 0.6;
    // Keep random bars inside the alert thresholds so only pinned shocks fire.
    move = Math.max(-0.035, Math.min(0.035, move));
    volumeMultiple = Math.min(volumeMultiple, 1.3);
    if (asset.shock && asset.shock.barsAgo === barsAgo) {
      move = asset.shock.move;
      volumeMultiple = asset.shock.volumeMultiple;
    }
    const close = open * (1 + move);
    const high = Math.max(open, close) * (1 + rng() * asset.volatility * 0.5);
    const low = Math.min(open, close) * (1 - rng() * asset.volatility * 0.5);
    bars.push({
      t: times[i],
      open: round(open, asset),
      high: round(high, asset),
      low: round(low, asset),
      close: round(close, asset),
      volume: Math.round(asset.baseVolume * volumeMultiple),
    });
    price = close;
  }
  return bars;
}

function round(value, asset) {
  const digits = asset.basePrice < 1 ? 4 : 2;
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

export function priceDecimals(price) {
  return price < 1 ? 4 : 2;
}

export function average(values) {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

function summarize(asset, history) {
  const last = history[history.length - 1];
  const prev = history[history.length - 2];
  const change = last.close - prev.close;
  const avgVolume20 = average(history.slice(-21, -1).map((b) => b.volume));
  return {
    ...asset,
    price: last.close,
    previousClose: prev.close,
    change: Math.round(change * 10000) / 10000,
    changePct: (change / prev.close) * 100,
    volume: last.volume,
    avgVolume20: Math.round(avgVolume20),
    asOf: last.t,
  };
}

function buildAlerts(assetSummaries, histories, news) {
  const alerts = [];
  for (const asset of assetSummaries) {
    const bars = histories[asset.symbol];
    for (let i = bars.length - ALERT_LOOKBACK_BARS; i < bars.length; i++) {
      const bar = bars[i];
      const prev = bars[i - 1];
      const changePct = ((bar.close - prev.close) / prev.close) * 100;
      if (Math.abs(changePct) >= PRICE_ALERT_THRESHOLD_PCT) {
        alerts.push({
          id: `price-${asset.symbol}-${bar.t}`,
          type: 'price',
          symbol: asset.symbol,
          time: bar.t,
          trigger: {
            changePct,
            fromPrice: prev.close,
            toPrice: bar.close,
            thresholdPct: PRICE_ALERT_THRESHOLD_PCT,
          },
        });
      }
      const avg = average(bars.slice(i - 20, i).map((b) => b.volume));
      const ratio = bar.volume / avg;
      if (ratio >= VOLUME_ALERT_MULTIPLE) {
        alerts.push({
          id: `volume-${asset.symbol}-${bar.t}`,
          type: 'volume',
          symbol: asset.symbol,
          time: bar.t,
          trigger: {
            volume: bar.volume,
            avgVolume20: Math.round(avg),
            ratio,
            thresholdMultiple: VOLUME_ALERT_MULTIPLE,
          },
        });
      }
    }
  }
  for (const item of news) {
    if (!item.alert) continue;
    for (const symbol of item.symbols) {
      alerts.push({
        id: `news-${item.id}-${symbol}`,
        type: 'news',
        symbol,
        time: item.publishedAt,
        trigger: { newsId: item.id, title: item.title, category: item.category },
      });
    }
  }
  return alerts.sort((a, b) => b.time - a.time);
}

// Builds the full, internally consistent demo dataset for one anchor time.
export function buildDemoDataset(now = new Date(), historyLength = 120) {
  const anchor = new Date(now);
  const histories = {};
  const assets = ASSETS.map((asset) => {
    const history = generateHistory(asset, historyLength, anchor);
    histories[asset.symbol] = history;
    return summarize(asset, history);
  });

  const news = NEWS_TEMPLATES.map((n) => ({
    ...n,
    publishedAt: Math.floor((anchor.getTime() - n.hoursAgo * HOUR_MS) / 60000) * 60000,
    demo: true,
  })).sort((a, b) => b.publishedAt - a.publishedAt);

  const dayStart = Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), anchor.getUTCDate());
  const events = EVENT_TEMPLATES.map((e) => ({
    ...e,
    time: dayStart + e.dayOffset * DAY_MS + e.hourUTC * HOUR_MS + e.minute * 60000,
    demo: true,
  })).sort((a, b) => a.time - b.time);

  const alerts = buildAlerts(assets, histories, news);

  return { generatedAt: anchor.getTime(), assets, histories, news, events, alerts };
}

// A manual alert for the "trigger demo event" button. It uses the asset's
// current demo values so the numbers match the rest of the interface.
export function makeManualDemoAlert(dataset, enabledTypes, rng = Math.random, now = Date.now()) {
  const types = ALERT_TYPES.filter((t) => enabledTypes.includes(t));
  if (types.length === 0) return null;
  const type = types[Math.floor(rng() * types.length)];
  const asset = dataset.assets[Math.floor(rng() * dataset.assets.length)];
  const id = `manual-${type}-${asset.symbol}-${now}-${Math.floor(rng() * 1e6)}`;
  const base = { id, type, symbol: asset.symbol, time: now, manual: true };
  if (type === 'price') {
    const sign = rng() < 0.5 ? -1 : 1;
    const changePct = sign * (PRICE_ALERT_THRESHOLD_PCT + rng() * 3);
    const toPrice = round(asset.price * (1 + changePct / 100), asset);
    return { ...base, trigger: { changePct, fromPrice: asset.price, toPrice, thresholdPct: PRICE_ALERT_THRESHOLD_PCT } };
  }
  if (type === 'volume') {
    const ratio = VOLUME_ALERT_MULTIPLE + rng() * 2;
    return { ...base, trigger: {
      volume: Math.round(asset.avgVolume20 * ratio), avgVolume20: asset.avgVolume20, ratio,
      thresholdMultiple: VOLUME_ALERT_MULTIPLE } };
  }
  return { ...base, trigger: {
    newsId: null,
    title: `ידיעת הדגמה שנוצרה ידנית עבור ${asset.name}`,
    category: 'מסחר ושוק' } };
}
