require('dotenv').config();
const path = require('path');

const nodeEnv = process.env.NODE_ENV || 'development';
const isProduction = nodeEnv === 'production';

function numberFromEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(`${name} must be a number, got "${raw}"`);
  return value;
}

let jwtSecret = process.env.JWT_SECRET;
if (!jwtSecret) {
  if (isProduction) throw new Error('JWT_SECRET is required in production');
  jwtSecret = 'dev-only-insecure-secret';
  console.warn('[config] JWT_SECRET is not set; using an insecure development secret');
}

const platformFeeRate = numberFromEnv('PLATFORM_FEE_RATE', 0.15);
if (platformFeeRate <= 0 || platformFeeRate >= 1) {
  throw new Error('PLATFORM_FEE_RATE must be between 0 and 1');
}

const stripeSecretKey = process.env.STRIPE_SECRET_KEY || '';
const stripeMockMode = !stripeSecretKey;
const allowDirectDeposit = stripeMockMode || process.env.ALLOW_DIRECT_DEPOSIT === 'true';
if (isProduction && allowDirectDeposit) {
  throw new Error('Direct wallet deposits must be disabled in production: set STRIPE_SECRET_KEY and ALLOW_DIRECT_DEPOSIT=false');
}

const twilio = {
  accountSid: process.env.TWILIO_ACCOUNT_SID || '',
  authToken: process.env.TWILIO_AUTH_TOKEN || '',
  verifyServiceSid: process.env.TWILIO_VERIFY_SERVICE_SID || '',
};
twilio.enabled = Boolean(twilio.accountSid && twilio.authToken && twilio.verifyServiceSid);

// SMS one-time codes on login and sign-up. Phone-only login lets anyone who
// knows a number sign in as its owner, so production refuses to start
// without OTP unless that risk is accepted explicitly.
const otpRequired = process.env.OTP_REQUIRED === 'true';
if (isProduction && !otpRequired && process.env.ALLOW_PHONE_ONLY_LOGIN !== 'true') {
  throw new Error('Set OTP_REQUIRED=true (with Twilio Verify credentials) in production, or ALLOW_PHONE_ONLY_LOGIN=true to accept the risk');
}
if (isProduction && otpRequired && !twilio.enabled) {
  throw new Error('OTP_REQUIRED=true in production needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_VERIFY_SERVICE_SID');
}

// Number of reverse proxies in front of the API (load balancer, ingress), so
// req.ip, and with it rate limiting, sees the real client address.
const trustProxy = numberFromEnv('TRUST_PROXY', 0);

module.exports = {
  nodeEnv,
  isProduction,
  port: numberFromEnv('PORT', 4000),
  frontendUrl: (process.env.FRONTEND_URL || 'http://localhost:3000').replace(/\/$/, ''),
  jwtSecret,
  jwtExpiresIn: '7d',
  platformFeeRate,
  currency: 'ils',
  allowDirectDeposit,
  otpRequired,
  twilio,
  trustProxy,
  // Uploaded problem photos. Use a persistent volume in production (or swap
  // the local driver in services/storageService.js for object storage).
  uploadDir: path.resolve(process.env.UPLOAD_DIR || path.join(__dirname, '..', 'uploads')),
  stripe: {
    secretKey: stripeSecretKey,
    webhookSecret: process.env.STRIPE_WEBHOOK_SECRET || '',
    mockMode: stripeMockMode,
  },
};
