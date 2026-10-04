// A final price under this share of the estimate is treated as a possible
// off-platform side deal (the client pays the rest in cash, dodging the fee).
const UNDERPRICE_RATIO = 0.5;
const SUSPEND_AFTER_FLAGS = 2;
const FLAG_WINDOW_DAYS = 30;

function isUnderpriced(estimatedCents, finalCents) {
  return finalCents < estimatedCents * UNDERPRICE_RATIO;
}

function shouldSuspend(flagsInWindow) {
  return flagsInWindow >= SUSPEND_AFTER_FLAGS;
}

function flagWindowStart(now = new Date()) {
  return new Date(now.getTime() - FLAG_WINDOW_DAYS * 24 * 60 * 60 * 1000);
}

function underpriceReason(estimatedCents, finalCents) {
  const pct = estimatedCents === 0 ? 0 : Math.round((finalCents / estimatedCents) * 100);
  return `Final price is ${pct}% of the estimate (threshold ${UNDERPRICE_RATIO * 100}%)`;
}

module.exports = {
  UNDERPRICE_RATIO,
  SUSPEND_AFTER_FLAGS,
  FLAG_WINDOW_DAYS,
  isUnderpriced,
  shouldSuspend,
  flagWindowStart,
  underpriceReason,
};
