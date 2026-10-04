require('dotenv').config();

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
  stripe: {
    secretKey: stripeSecretKey,
    webhookSecret: process.env.STRIPE_WEBHOOK_SECRET || '',
    mockMode: stripeMockMode,
  },
};
