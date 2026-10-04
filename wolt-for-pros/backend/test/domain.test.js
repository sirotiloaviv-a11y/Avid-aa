// Pure business rules: no database or network needed. Run with `npm test`.
const test = require('node:test');
const assert = require('node:assert/strict');
const { toCents, fromCents, toNumber } = require('../src/domain/money');
const { estimateFor, feeCents, settlement, generateCompletionCode, catalog } = require('../src/domain/pricing');
const { isUnderpriced, shouldSuspend, flagWindowStart, underpriceReason } = require('../src/domain/fraud');
const { haversineKm, etaMinutes, isValidCoordinate } = require('../src/domain/geo');

test('money converts without floating-point drift', () => {
  assert.equal(toCents('67.50'), 6750);
  assert.equal(toCents(0.1 + 0.2), 30);
  assert.equal(toCents({ toString: () => '12.34' }), 1234); // Prisma Decimal
  assert.equal(fromCents(6750), '67.50');
  assert.equal(fromCents(-5), '-0.05');
  assert.equal(fromCents(0), '0.00');
  assert.equal(toNumber('199.99'), 199.99);
  assert.equal(toNumber(null), null);
  assert.throws(() => toCents('abc'));
  assert.throws(() => fromCents(1.5));
});

test('estimate is the midpoint of the service range', () => {
  assert.equal(estimateFor('electrician').estimate, 450);
  assert.equal(estimateFor('plumber').estimate, 525);
  assert.equal(estimateFor('handyman').estimate, 315);
  assert.equal(catalog().length, 3);
  assert.throws(() => estimateFor('roofer'));
});

test('fee is 15% of the price, rounded to the agora', () => {
  assert.equal(feeCents(45000, 0.15), 6750);
  assert.equal(feeCents(52500, 0.15), 7875);
  assert.equal(feeCents(33333, 0.15), 5000);
  assert.throws(() => feeCents(-1, 0.15));
});

test('settlement releases the whole hold and charges the final fee', () => {
  // Final fee below the hold: the difference returns to available.
  assert.deepEqual(settlement(6750, 6000), { lockedDelta: -6750, availableDelta: 750, chargedCents: 6000, releasedCents: 750 });
  // Final fee above the hold: the excess comes out of available.
  assert.deepEqual(settlement(6750, 9000), { lockedDelta: -6750, availableDelta: -2250, chargedCents: 9000, releasedCents: 0 });
  // Exact.
  assert.deepEqual(settlement(6750, 6750), { lockedDelta: -6750, availableDelta: 0, chargedCents: 6750, releasedCents: 0 });
});

test('completion code is always 4 digits', () => {
  assert.equal(generateCompletionCode(() => 7), '0007');
  assert.equal(generateCompletionCode(() => 9999), '9999');
  const crypto = require('crypto');
  for (let i = 0; i < 200; i += 1) assert.match(generateCompletionCode(crypto.randomInt), /^\d{4}$/);
});

test('jobs closed under 50% of the estimate are underpriced', () => {
  assert.equal(isUnderpriced(45000, 15000), true);
  assert.equal(isUnderpriced(45000, 22499), true);
  assert.equal(isUnderpriced(45000, 22500), false); // exactly 50% is fine
  assert.equal(isUnderpriced(45000, 60000), false);
  assert.match(underpriceReason(45000, 15000), /33%/);
});

test('two flags in the window suspend', () => {
  assert.equal(shouldSuspend(1), false);
  assert.equal(shouldSuspend(2), true);
  assert.equal(shouldSuspend(5), true);
  const now = new Date('2026-10-04T00:00:00Z');
  assert.equal(flagWindowStart(now).toISOString(), '2026-09-04T00:00:00.000Z');
});

test('geo helpers', () => {
  const telAviv = { lat: 32.0853, lng: 34.7818 };
  const jerusalem = { lat: 31.7683, lng: 35.2137 };
  const d = haversineKm(telAviv, jerusalem);
  assert.ok(d > 50 && d < 56, `distance was ${d}`);
  assert.equal(etaMinutes(15), 30);
  assert.equal(etaMinutes(0), 0);
  assert.equal(isValidCoordinate(32, 34), true);
  assert.equal(isValidCoordinate(91, 34), false);
  assert.equal(isValidCoordinate(NaN, 34), false);
});
