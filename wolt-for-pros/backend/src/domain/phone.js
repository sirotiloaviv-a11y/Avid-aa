// Phone numbers are stored as typed (e.g. "0501234567") but SMS providers
// need E.164 ("+972501234567"). Israeli local numbers are assumed when there
// is no country code.
const DEFAULT_COUNTRY_CODE = '972';

function toE164(phone, countryCode = DEFAULT_COUNTRY_CODE) {
  const raw = String(phone || '').trim();
  const digits = raw.replace(/[^\d]/g, '');
  if (!digits) throw new RangeError('Phone number is empty');
  let e164;
  if (raw.startsWith('+')) e164 = `+${digits}`;
  else if (digits.startsWith('00')) e164 = `+${digits.slice(2)}`;
  else if (digits.startsWith(countryCode)) e164 = `+${digits}`;
  else if (digits.startsWith('0')) e164 = `+${countryCode}${digits.slice(1)}`;
  else e164 = `+${countryCode}${digits}`;
  if (!/^\+[1-9]\d{7,14}$/.test(e164)) throw new RangeError(`Not a valid phone number: ${phone}`);
  return e164;
}

// "+972501234567" -> "+97250***4567" for logs.
function maskPhone(e164) {
  return e164.length > 8 ? `${e164.slice(0, 6)}***${e164.slice(-4)}` : '***';
}

module.exports = { toE164, maskPhone };
