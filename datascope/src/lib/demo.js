/**
 * Deterministic demonstration data for DEMO_A, DEMO_B and DEMO_C.
 *
 * These numbers are invented. They are produced by a fixed seeded generator in
 * this file, they do not describe any real company, security or market, and they
 * are not derived from any data source - remembered, fetched or otherwise. The UI
 * labels them as invented wherever they appear.
 *
 * The generator is seeded and uses only integer arithmetic plus a fixed rounding
 * step, so the same rows come out on every run, in every browser and in Node.
 * That is what makes the demo testable: tests assert exact values.
 */

const START_DATE = '2024-01-02';
const END_DATE = '2024-12-31';

/** Fixed "market closed" weekdays, so the demo has real gaps in the calendar. */
const CLOSED_WEEKDAYS = new Set([
  '2024-01-15',
  '2024-02-19',
  '2024-03-29',
  '2024-05-27',
  '2024-06-19',
  '2024-07-04',
  '2024-09-02',
  '2024-11-28',
  '2024-12-25',
]);

const SERIES = Object.freeze([
  // The drifts are picked so the three demo series trend differently - up, down
  // and roughly flat - which is what makes them useful for demonstrating the UI.
  { symbol: 'DEMO_A', seed: 0x5eed_0a01, startClose: 100, drift: 0.0012, volatility: 0.011, baseVolume: 1_250_000 },
  { symbol: 'DEMO_B', seed: 0x5eed_0b02, startClose: 42.5, drift: -0.0008, volatility: 0.018, baseVolume: 480_000 },
  { symbol: 'DEMO_C', seed: 0x5eed_0c03, startClose: 250, drift: 0.0004, volatility: 0.007, baseVolume: 95_000 },
]);

export const DEMO_SYMBOLS = Object.freeze(SERIES.map((series) => series.symbol));
export const DEMO_FILE_NAME = 'datascope_demo_data.csv';
export const DEMO_LABEL = 'נתוני הדגמה מומצאים';

/** mulberry32 - small, fast, fully determined by its 32-bit seed. */
function createRandom(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6d2b_79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function isoToUtcMillis(iso) {
  return Date.UTC(
    Number(iso.slice(0, 4)),
    Number(iso.slice(5, 7)) - 1,
    Number(iso.slice(8, 10)),
  );
}

function utcMillisToIso(millis) {
  return new Date(millis).toISOString().slice(0, 10);
}

/**
 * Trading days of the demo calendar: weekdays minus a fixed closed-day list.
 * @returns {string[]} ISO dates, ascending.
 */
export function demoTradingDays() {
  const days = [];
  const end = isoToUtcMillis(END_DATE);
  for (let stamp = isoToUtcMillis(START_DATE); stamp <= end; stamp += 86_400_000) {
    const date = new Date(stamp);
    const weekday = date.getUTCDay(); // 0 = Sunday, 6 = Saturday
    if (weekday === 0 || weekday === 6) continue;
    const iso = utcMillisToIso(stamp);
    if (CLOSED_WEEKDAYS.has(iso)) continue;
    days.push(iso);
  }
  return days;
}

/**
 * @returns {{date: string, symbol: string, close: number, volume: number}[]}
 *   Grouped by symbol rather than by date - real exports often are, and it lets
 *   the demo exercise the "rows were reordered chronologically" notice.
 */
export function generateDemoRows() {
  const days = demoTradingDays();
  const rows = [];

  for (const series of SERIES) {
    const random = createRandom(series.seed);
    let close = series.startClose;
    for (const date of days) {
      // Round each close to two decimals before it feeds the next step, so the
      // sequence is defined by the rounded values and cannot drift.
      const shock = (random() * 2 - 1) * series.volatility + series.drift;
      close = Math.max(1, Math.round(close * (1 + shock) * 100) / 100);
      const volume = Math.round(series.baseVolume * (0.6 + random() * 0.9));
      rows.push({ date, symbol: series.symbol, close, volume });
    }
  }

  return rows;
}

/**
 * The same rows as CSV text, in the import format. Used by "הורדת CSV לדוגמה"
 * and by the tests, so the download and the in-app demo can never diverge.
 * @returns {string}
 */
export function generateDemoCsv() {
  const lines = ['date,symbol,close,volume'];
  for (const row of generateDemoRows()) {
    lines.push(`${row.date},${row.symbol},${row.close},${row.volume}`);
  }
  return `${lines.join('\n')}\n`;
}
