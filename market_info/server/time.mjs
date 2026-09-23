// Time-zone arithmetic without dependencies, and US equity session rules.
const NY = 'America/New_York';
const OPEN_MIN = 9 * 60 + 30;
const CLOSE_MIN = 16 * 60;

export function tzOffsetMinutes(tz, ms) {
  const raw = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'longOffset' })
    .formatToParts(new Date(ms)).find((p) => p.type === 'timeZoneName')?.value ?? 'GMT';
  const m = /GMT([+-])(\d{2}):(\d{2})/.exec(raw);
  if (!m) return 0;
  return (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]));
}

// "2026-09-22", 16, 0, "America/New_York" -> epoch ms of that local wall time.
export function zonedTimeToUtc(dateKey, hour, minute, tz) {
  const [y, mo, d] = dateKey.split('-').map(Number);
  const guess = Date.UTC(y, mo - 1, d, hour, minute);
  let ms = guess - tzOffsetMinutes(tz, guess) * 60000;
  const check = guess - tzOffsetMinutes(tz, ms) * 60000;
  if (check !== ms) ms = check;
  return ms;
}

function nyParts(now) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: NY, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    weekday: 'short', hourCycle: 'h23',
  }).formatToParts(new Date(now)).map((p) => [p.type, p.value]));
  return {
    dateKey: `${parts.year}-${parts.month}-${parts.day}`,
    weekday: parts.weekday,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

const isWeekendName = (w) => w === 'Sat' || w === 'Sun';

export function addDaysKey(key, days) {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function weekdayOfKey(key) {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

// Regular-hours status only; exchange holidays and half days are not modeled.
export function usMarketSession(now = Date.now()) {
  const p = nyParts(now);
  if (isWeekendName(p.weekday)) return { state: 'closed', reason: 'weekend' };
  if (p.minutes < OPEN_MIN) return { state: 'closed', reason: 'pre_open' };
  if (p.minutes >= CLOSE_MIN) return { state: 'closed', reason: 'after_close' };
  return { state: 'open', reason: 'regular_hours' };
}

// The most recent weekday whose regular session has already closed.
export function lastCompletedSessionDate(now = Date.now()) {
  const p = nyParts(now);
  let key = p.dateKey;
  if (!isWeekendName(p.weekday) && p.minutes >= CLOSE_MIN) return key;
  do { key = addDaysKey(key, -1); } while ([0, 6].includes(weekdayOfKey(key)));
  return key;
}

export function weekdaysBetween(fromKey, toKey) {
  let count = 0;
  let key = fromKey;
  while (key < toKey) {
    key = addDaysKey(key, 1);
    if (![0, 6].includes(weekdayOfKey(key))) count++;
  }
  return count;
}

// A daily stock series is "old" if it misses more than one expected session.
// One missing session is tolerated for holidays and provider update lag.
export function isStockSeriesOld(lastBarKey, now = Date.now()) {
  return weekdaysBetween(lastBarKey, lastCompletedSessionDate(now)) > 1;
}

export function nyDateKey(now = Date.now()) {
  return nyParts(now).dateKey;
}
