/**
 * The alert engine.
 *
 * Everything here is pure: `runAlertEngine()` takes rules, a way to look up the
 * current state of an asset, and the time, and returns new rules plus the events
 * that fired. It sends no notification and touches no DOM, which is what makes
 * every triggering rule in the tests reproducible to the millisecond.
 *
 * The part that matters most is not "does the condition hold" but "should this
 * fire *now*". A naive engine that alerts whenever price >= target sends a
 * notification on every tick for the rest of the day. Two mechanisms prevent
 * that:
 *
 *   - Edge triggering. A rule fires on the transition from unmet to met, then
 *     disarms. It re-arms only when the condition stops holding.
 *   - A cooldown. Re-arming alone is not enough for a price hovering on the
 *     threshold, which would otherwise flap once per tick, so a rule also cannot
 *     fire again until its cooldown has elapsed.
 */

import { percentChange } from './model.js';
import { formatPercent, formatPrice, formatCompact, formatClock } from './format.js';

export const RULE_TYPE = Object.freeze({
  PRICE: 'price',
  PERCENT: 'percent',
  VOLUME: 'volume',
});

export const RULE_TYPE_LABELS = Object.freeze({
  [RULE_TYPE.PRICE]: 'מחיר יעד',
  [RULE_TYPE.PERCENT]: 'זינוק באחוזים',
  [RULE_TYPE.VOLUME]: 'זינוק במחזור',
});

export const DEFAULT_COOLDOWN_MS = 5 * 60_000;

/** Minimum share of baseline buckets required before a volume rule may fire. */
const MIN_BASELINE_COVERAGE = 0.5;

/**
 * @typedef {object} AlertRule
 * @property {string} id
 * @property {string} assetKey
 * @property {'price'|'percent'|'volume'} type
 * @property {'above'|'below'} [direction] Price rules.
 * @property {number} [target] Price rules.
 * @property {number} [thresholdPct] Percent rules, magnitude.
 * @property {'up'|'down'|'both'} [move] Percent rules.
 * @property {'window'|'dayOpen'} [basis] Percent rules.
 * @property {number} [windowMs] Percent and volume rules.
 * @property {number} [multiple] Volume rules.
 * @property {number} [baselineWindows] Volume rules.
 * @property {boolean} enabled
 * @property {number} cooldownMs
 * @property {boolean} armed
 * @property {number|null} lastTriggeredAt
 * @property {number} triggerCount
 * @property {number} createdAt
 * @property {string} note
 */

let idCounter = 0;

/**
 * Ids only have to be unique inside one browser tab. Time plus a counter is
 * enough and keeps rules readable in storage; crypto.randomUUID is used when
 * available.
 */
function makeId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  idCounter += 1;
  return `rule-${Date.now().toString(36)}-${idCounter}`;
}

/**
 * Builds a rule with every field filled in, so no consumer has to guess a
 * default. Unknown fields are dropped rather than carried.
 * @param {Partial<AlertRule> & {assetKey: string, type: string}} input
 * @returns {AlertRule}
 */
export function createRule(input) {
  const base = {
    id: input.id ?? makeId(),
    assetKey: input.assetKey,
    type: input.type,
    enabled: input.enabled ?? true,
    cooldownMs: numberOr(input.cooldownMs, DEFAULT_COOLDOWN_MS),
    armed: input.armed ?? true,
    lastTriggeredAt: input.lastTriggeredAt ?? null,
    triggerCount: numberOr(input.triggerCount, 0),
    createdAt: numberOr(input.createdAt, Date.now()),
    note: typeof input.note === 'string' ? input.note.slice(0, 120) : '',
  };

  switch (input.type) {
    case RULE_TYPE.PRICE:
      return {
        ...base,
        direction: input.direction === 'below' ? 'below' : 'above',
        target: numberOr(input.target, 0),
      };
    case RULE_TYPE.PERCENT:
      return {
        ...base,
        thresholdPct: Math.abs(numberOr(input.thresholdPct, 2)),
        move: ['up', 'down', 'both'].includes(input.move) ? input.move : 'both',
        basis: input.basis === 'dayOpen' ? 'dayOpen' : 'window',
        windowMs: numberOr(input.windowMs, 5 * 60_000),
      };
    case RULE_TYPE.VOLUME:
      return {
        ...base,
        multiple: numberOr(input.multiple, 3),
        windowMs: numberOr(input.windowMs, 5 * 60_000),
        baselineWindows: Math.max(2, Math.round(numberOr(input.baselineWindows, 12))),
      };
    default:
      throw new Error(`Unknown rule type: ${input.type}`);
  }
}

/**
 * Form validation. Returns Hebrew messages keyed by field, empty when valid.
 * @param {Partial<AlertRule>} input
 * @returns {Record<string, string>}
 */
export function validateRule(input) {
  /** @type {Record<string, string>} */
  const errors = {};
  if (!input.assetKey) errors.assetKey = 'יש לבחור נכס.';

  if (input.type === RULE_TYPE.PRICE) {
    const target = Number(input.target);
    if (!Number.isFinite(target) || target <= 0) {
      errors.target = 'מחיר היעד חייב להיות מספר חיובי.';
    }
  } else if (input.type === RULE_TYPE.PERCENT) {
    const pct = Number(input.thresholdPct);
    if (!Number.isFinite(pct) || pct <= 0) {
      errors.thresholdPct = 'אחוז השינוי חייב להיות מספר חיובי.';
    } else if (pct > 100) {
      errors.thresholdPct = 'אחוז השינוי גדול מ־100% ולא יופעל בפועל.';
    }
    if (input.basis !== 'dayOpen') {
      const window = Number(input.windowMs);
      if (!Number.isFinite(window) || window < 60_000) {
        errors.windowMs = 'חלון הזמן המזערי הוא דקה אחת.';
      }
    }
  } else if (input.type === RULE_TYPE.VOLUME) {
    const multiple = Number(input.multiple);
    if (!Number.isFinite(multiple) || multiple <= 1) {
      errors.multiple = 'הכפולה חייבת להיות גדולה מ־1 (למשל 3 = פי שלושה מהממוצע).';
    }
    const window = Number(input.windowMs);
    if (!Number.isFinite(window) || window < 60_000) {
      errors.windowMs = 'חלון הזמן המזערי הוא דקה אחת.';
    }
  } else {
    errors.type = 'סוג התראה לא מוכר.';
  }

  return errors;
}

/**
 * Evaluates one rule against the current state.
 *
 * @param {AlertRule} rule
 * @param {{quote: import('./model.js').Quote|null, series: import('./series.js').Series|null}} context
 * @param {number} now Epoch ms.
 * @returns {{met: boolean, value: number|null, reason: string|null, detail: object}}
 *   `reason` explains a *non*-evaluation (missing data), which the UI surfaces
 *   so a rule that can never fire does not sit there looking healthy.
 */
export function evaluateRule(rule, context, now) {
  const price = context?.quote?.price ?? context?.series?.lastPrice ?? null;
  if (price === null) {
    return { met: false, value: null, reason: 'אין עדיין מחיר עבור הנכס', detail: {} };
  }

  switch (rule.type) {
    case RULE_TYPE.PRICE: {
      const met = rule.direction === 'below' ? price <= rule.target : price >= rule.target;
      return { met, value: price, reason: null, detail: { price, target: rule.target } };
    }

    case RULE_TYPE.PERCENT: {
      let base = null;
      if (rule.basis === 'dayOpen') {
        base = context.quote?.open ?? context.quote?.prevClose ?? null;
        if (base === null) {
          return { met: false, value: null, reason: 'אין מחיר פתיחה להשוואה', detail: {} };
        }
      } else {
        const series = context.series;
        base = series ? series.priceAt(now - rule.windowMs) : null;
        if (base === null) {
          return {
            met: false,
            value: null,
            reason: 'אין מספיק היסטוריה לחלון הזמן שנבחר',
            detail: {},
          };
        }
      }
      const change = percentChange(base, price);
      if (change === null) {
        return { met: false, value: null, reason: 'לא ניתן לחשב שינוי', detail: {} };
      }
      const met =
        rule.move === 'up'
          ? change >= rule.thresholdPct
          : rule.move === 'down'
            ? change <= -rule.thresholdPct
            : Math.abs(change) >= rule.thresholdPct;
      return { met, value: change, reason: null, detail: { base, price, change } };
    }

    case RULE_TYPE.VOLUME: {
      const series = context.series;
      if (!series) {
        return { met: false, value: null, reason: 'אין נתוני מחזור עבור הנכס', detail: {} };
      }
      const bucketMs = series.bucketMs;
      const windowBuckets = Math.max(1, Math.round(rule.windowMs / bucketMs));
      const windowStart = now - rule.windowMs;
      const baselineStart = windowStart - rule.windowMs * rule.baselineWindows;

      const observedBuckets = series.window(baselineStart, windowStart).length;
      const requiredBuckets = Math.ceil(windowBuckets * rule.baselineWindows * MIN_BASELINE_COVERAGE);
      if (observedBuckets < requiredBuckets) {
        return {
          met: false,
          value: null,
          reason: 'אין מספיק היסטוריית מחזור לחישוב ממוצע',
          detail: { observedBuckets, requiredBuckets },
        };
      }

      const averagePerBucket = series.averageVolume(baselineStart, windowStart);
      if (averagePerBucket === null || averagePerBucket <= 0) {
        return { met: false, value: null, reason: 'ממוצע המחזור ההיסטורי הוא אפס', detail: {} };
      }

      const windowVolume = series.volumeSince(windowStart);
      const baselineVolume = averagePerBucket * windowBuckets;
      const ratio = windowVolume / baselineVolume;
      return {
        met: ratio >= rule.multiple,
        value: ratio,
        reason: null,
        detail: { windowVolume, baselineVolume, ratio },
      };
    }

    default:
      return { met: false, value: null, reason: 'סוג התראה לא מוכר', detail: {} };
  }
}

/**
 * Runs every rule and decides which ones fire.
 *
 * Pure: the rules passed in are not mutated. The caller replaces its list with
 * the returned one.
 *
 * @param {object} input
 * @param {AlertRule[]} input.rules
 * @param {(assetKey: string) => {quote: any, series: any, asset: any}|null} input.contextFor
 * @param {number} input.now
 * @returns {{rules: AlertRule[], events: AlertEvent[], diagnostics: Record<string, string|null>}}
 */
export function runAlertEngine({ rules, contextFor, now }) {
  /** @type {AlertRule[]} */
  const nextRules = [];
  /** @type {AlertEvent[]} */
  const events = [];
  /** @type {Record<string, string|null>} */
  const diagnostics = {};

  for (const rule of rules) {
    if (!rule.enabled) {
      nextRules.push(rule);
      diagnostics[rule.id] = null;
      continue;
    }

    const context = contextFor(rule.assetKey);
    if (!context) {
      nextRules.push(rule);
      diagnostics[rule.id] = 'הנכס אינו נמצא ברשימת המעקב';
      continue;
    }

    const outcome = evaluateRule(rule, context, now);
    diagnostics[rule.id] = outcome.reason;

    if (!outcome.met) {
      // Re-arm as soon as the condition stops holding.
      nextRules.push(rule.armed ? rule : { ...rule, armed: true });
      continue;
    }

    const cooledDown =
      rule.lastTriggeredAt === null || now - rule.lastTriggeredAt >= rule.cooldownMs;

    if (rule.armed && cooledDown) {
      const fired = {
        ...rule,
        armed: false,
        lastTriggeredAt: now,
        triggerCount: rule.triggerCount + 1,
      };
      nextRules.push(fired);
      events.push(buildEvent(fired, context, outcome, now));
    } else {
      nextRules.push(rule);
    }
  }

  return { rules: nextRules, events, diagnostics };
}

/**
 * @typedef {object} AlertEvent
 * @property {string} id
 * @property {string} ruleId
 * @property {string} assetKey
 * @property {string} symbol
 * @property {string} displaySymbol
 * @property {string|null} name
 * @property {string} title Notification title: "Apple Inc. / AAPL".
 * @property {string} body Notification body, Hebrew.
 * @property {string} ruleLabel
 * @property {number|null} price
 * @property {number|null} value
 * @property {number} ts
 * @property {string} type
 */

function buildEvent(rule, context, outcome, now) {
  const asset = context.asset ?? {};
  const displaySymbol = asset.displaySymbol ?? asset.symbol ?? rule.assetKey;
  const price = context.quote?.price ?? context.series?.lastPrice ?? null;

  return {
    id: makeId(),
    ruleId: rule.id,
    assetKey: rule.assetKey,
    symbol: asset.symbol ?? rule.assetKey,
    displaySymbol,
    name: asset.name ?? null,
    // The requirement is that every notification carries the full name *and* the
    // symbol. When a provider has not resolved a name we show the symbol alone
    // rather than inventing one.
    title: asset.name ? `${asset.name} / ${displaySymbol}` : displaySymbol,
    body: describeTrigger(rule, outcome, price, now),
    ruleLabel: describeRule(rule),
    price,
    value: outcome.value,
    ts: now,
    type: rule.type,
  };
}

/**
 * A one-line Hebrew description of what a rule watches. Used in the rule list,
 * in the history and inside the notification.
 * @param {AlertRule} rule
 */
export function describeRule(rule) {
  switch (rule.type) {
    case RULE_TYPE.PRICE:
      return rule.direction === 'below'
        ? `מחיר יורד אל ${formatPrice(rule.target)} או מתחת`
        : `מחיר עולה אל ${formatPrice(rule.target)} או מעל`;
    case RULE_TYPE.PERCENT: {
      const scope =
        rule.basis === 'dayOpen' ? 'מאז פתיחת היום' : `בתוך ${formatMinutes(rule.windowMs)}`;
      const direction =
        rule.move === 'up' ? 'עלייה של' : rule.move === 'down' ? 'ירידה של' : 'שינוי של';
      return `${direction} ${formatPercentPlain(rule.thresholdPct)} ${scope}`;
    }
    case RULE_TYPE.VOLUME:
      return `מחזור גבוה פי ${formatNumberPlain(rule.multiple)} מהממוצע, בחלון של ${formatMinutes(
        rule.windowMs,
      )}`;
    default:
      return 'כלל לא מוכר';
  }
}

/**
 * The notification body: what happened, with the number that caused it.
 * @param {AlertRule} rule
 * @param {{value: number|null, detail: any}} outcome
 * @param {number|null} price
 * @param {number} now
 */
export function describeTrigger(rule, outcome, price, now) {
  const time = formatClock(now);
  switch (rule.type) {
    case RULE_TYPE.PRICE:
      return `המחיר ${formatPrice(price)} ${
        rule.direction === 'below' ? 'ירד אל היעד' : 'עלה אל היעד'
      } ${formatPrice(rule.target)} · ${time}`;
    case RULE_TYPE.PERCENT: {
      const scope =
        rule.basis === 'dayOpen' ? 'מאז פתיחת היום' : `ב־${formatMinutes(rule.windowMs)} האחרונות`;
      return `שינוי של ${formatPercent(outcome.value)} ${scope} · מחיר ${formatPrice(price)} · ${time}`;
    }
    case RULE_TYPE.VOLUME:
      return `המחזור גבוה פי ${formatNumberPlain(outcome.value)} מהממוצע (${formatCompact(
        outcome.detail?.windowVolume ?? 0,
      )} מול ${formatCompact(outcome.detail?.baselineVolume ?? 0)}) · מחיר ${formatPrice(
        price,
      )} · ${time}`;
    default:
      return `התראה הופעלה · ${time}`;
  }
}

function formatMinutes(ms) {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes} דקות`;
  const hours = Math.round((minutes / 60) * 10) / 10;
  return `${hours} שעות`;
}

function formatPercentPlain(value) {
  return `${Math.round(value * 100) / 100}%`;
}

function formatNumberPlain(value) {
  if (value === null || !Number.isFinite(value)) return '—';
  return String(Math.round(value * 100) / 100);
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * A bounded log of everything that fired. Bounded because this runs for hours:
 * a dashboard left open overnight must not accumulate an unbounded array.
 */
export class AlertHistory {
  /** @param {number} [capacity] */
  constructor(capacity = 200) {
    this.capacity = capacity;
    /** @type {AlertEvent[]} Newest first. */
    this.entries = [];
  }

  /** @param {AlertEvent[]} events */
  add(events) {
    if (events.length === 0) return;
    this.entries.unshift(...events.slice().reverse());
    if (this.entries.length > this.capacity) {
      this.entries.length = this.capacity;
    }
  }

  clear() {
    this.entries = [];
  }

  get length() {
    return this.entries.length;
  }

  /** @param {AlertEvent[]} entries */
  static from(entries, capacity = 200) {
    const history = new AlertHistory(capacity);
    history.entries = Array.isArray(entries) ? entries.slice(0, capacity) : [];
    return history;
  }
}
