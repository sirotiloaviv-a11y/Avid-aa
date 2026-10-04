const { SERVICE_TYPES } = require('./constants');

// Typical call-out price ranges in shekels. The midpoint is the estimate the
// platform fee is held against when a tradesperson accepts.
const SERVICE_CATALOG = {
  electrician: { label: 'Electrician', min: 250, max: 650 },
  plumber: { label: 'Plumber', min: 300, max: 750 },
  handyman: { label: 'Handyman', min: 180, max: 450 },
};

function estimateFor(serviceType) {
  const entry = SERVICE_CATALOG[serviceType];
  if (!entry) throw new RangeError(`Unknown service type: ${serviceType}`);
  return { ...entry, estimate: Math.round((entry.min + entry.max) / 2) };
}

function catalog() {
  return SERVICE_TYPES.map((type) => ({ type, ...estimateFor(type) }));
}

function feeCents(priceCents, rate) {
  if (!Number.isInteger(priceCents) || priceCents < 0) {
    throw new RangeError(`Price must be a non-negative integer of cents, got ${priceCents}`);
  }
  return Math.round(priceCents * rate);
}

// Settling a job releases the whole hold and charges the fee on the final
// price. If the fee is smaller than the hold, the difference goes back to the
// available balance; if larger, the excess comes out of the available balance
// (which may go negative, blocking new jobs until the tradesperson tops up).
function settlement(heldCents, finalFeeCents) {
  return {
    lockedDelta: -heldCents,
    availableDelta: heldCents - finalFeeCents,
    chargedCents: finalFeeCents,
    releasedCents: Math.max(0, heldCents - finalFeeCents),
  };
}

function generateCompletionCode(randomInt) {
  return String(randomInt(0, 10000)).padStart(4, '0');
}

module.exports = {
  SERVICE_CATALOG,
  estimateFor,
  catalog,
  feeCents,
  settlement,
  generateCompletionCode,
};
