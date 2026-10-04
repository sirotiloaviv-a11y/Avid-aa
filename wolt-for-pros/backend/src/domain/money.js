// Money is stored as Decimal and handled in code as integer agorot ("cents")
// so fee arithmetic never touches binary floating point.

function toCents(value) {
  if (value === null || value === undefined) throw new TypeError('Money amount is missing');
  const n = typeof value === 'object' ? Number(value.toString()) : Number(value);
  if (!Number.isFinite(n)) throw new TypeError(`Invalid money amount: ${value}`);
  return Math.round(n * 100);
}

// Decimal-safe string ("-12.05") accepted by Prisma for Decimal columns.
function fromCents(cents) {
  if (!Number.isInteger(cents)) throw new TypeError(`Cents must be an integer, got ${cents}`);
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
}

function toNumber(value) {
  if (value === null || value === undefined) return null;
  return toCents(value) / 100;
}

module.exports = { toCents, fromCents, toNumber };
