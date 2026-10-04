// One-time login codes over SMS.
//
// Production: Twilio Verify (https://www.twilio.com/docs/verify/api). Twilio
// generates, sends and checks the code, so codes never touch our database.
// Called over plain HTTPS to avoid an SDK dependency.
//
// Development (no Twilio credentials): codes are generated in memory and
// printed to the server log, so the whole flow works offline.
const crypto = require('crypto');
const config = require('../config');
const { HttpError } = require('../middleware/errors');
const { toE164, maskPhone } = require('../domain/phone');

const DEV_CODE_TTL_MS = 5 * 60 * 1000;
const DEV_MAX_ATTEMPTS = 5;
const TWILIO_TIMEOUT_MS = 10000;

const devCodes = new Map(); // e164 -> { code, expiresAt, attempts }

function normalise(phone) {
  try {
    return toE164(phone);
  } catch (err) {
    throw new HttpError(400, err.message, 'BAD_PHONE');
  }
}

/** @returns {Promise<any>} Twilio's JSON response */
async function twilio(path, params) {
  const { accountSid, authToken, verifyServiceSid } = config.twilio;
  const auth = Buffer.from(`${accountSid}:${authToken}`).toString('base64');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TWILIO_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(`https://verify.twilio.com/v2/Services/${verifyServiceSid}/${path}`, {
      method: 'POST',
      headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(params),
      signal: controller.signal,
    });
  } catch (err) {
    console.error('[sms] Twilio request failed', err.message);
    throw new HttpError(502, 'Could not reach the SMS provider. Try again in a moment.', 'SMS_UNAVAILABLE');
  } finally {
    clearTimeout(timer);
  }
  /** @type {any} */
  const body = await res.json().catch(() => ({}));
  // 404 from VerificationCheck means no pending verification (expired or
  // already used): treat it as a wrong code rather than a server error.
  if (res.status === 404 && path === 'VerificationCheck') return { status: 'not_found' };
  if (res.status === 429 || body.code === 60203) {
    throw new HttpError(429, 'Too many codes requested for this number. Wait a few minutes.', 'SMS_RATE_LIMITED');
  }
  if (!res.ok) {
    console.error('[sms] Twilio error', res.status, body.code, body.message);
    throw new HttpError(502, 'The SMS provider rejected the request.', 'SMS_FAILED');
  }
  return body;
}

async function sendCode(phone) {
  const to = normalise(phone);
  if (config.twilio.enabled) {
    await twilio('Verifications', { To: to, Channel: 'sms' });
    return { sent: true };
  }
  const code = String(crypto.randomInt(0, 1000000)).padStart(6, '0');
  devCodes.set(to, { code, expiresAt: Date.now() + DEV_CODE_TTL_MS, attempts: 0 });
  console.log(`[sms:dev] login code for ${maskPhone(to)}: ${code}`);
  // Outside production the code is also returned so the UI can show it.
  return { sent: true, devCode: config.isProduction ? undefined : code };
}

async function checkCode(phone, code) {
  const to = normalise(phone);
  if (!/^\d{4,8}$/.test(String(code || ''))) return false;
  if (config.twilio.enabled) {
    const result = await twilio('VerificationCheck', { To: to, Code: String(code) });
    return result.status === 'approved';
  }
  const entry = devCodes.get(to);
  if (!entry || entry.expiresAt < Date.now()) {
    devCodes.delete(to);
    return false;
  }
  entry.attempts += 1;
  if (entry.attempts > DEV_MAX_ATTEMPTS) {
    devCodes.delete(to);
    return false;
  }
  const given = String(code);
  const ok = given.length === entry.code.length && crypto.timingSafeEqual(Buffer.from(entry.code), Buffer.from(given));
  if (ok) devCodes.delete(to);
  return ok;
}

// Throws unless OTP is disabled or the code checks out.
async function assertVerified(phone, otpCode) {
  if (!config.otpRequired) return;
  if (!otpCode) throw new HttpError(401, 'Enter the code we sent to your phone', 'OTP_REQUIRED');
  if (!(await checkCode(phone, otpCode))) throw new HttpError(401, 'That code is wrong or has expired', 'INVALID_OTP');
}

function _resetDevCodes() {
  devCodes.clear();
}

module.exports = { sendCode, checkCode, assertVerified, _resetDevCodes };
