const express = require('express');
const { z } = require('zod');
const config = require('../config');
const { prisma } = require('../db');
const { asyncHandler, parse, HttpError } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const { TOP_UP_MIN, TOP_UP_MAX } = require('../domain/constants');
const { toCents } = require('../domain/money');
const walletService = require('../services/walletService');
const stripeService = require('../services/stripeService');
const { serializeWallet, serializeTransaction } = require('../serializers');

const router = express.Router();
router.use(authenticate, requireRole('tradesperson'));

const amountSchema = z.object({
  amount: z.coerce.number().int('Whole shekels only').min(TOP_UP_MIN).max(TOP_UP_MAX),
});

async function walletFor(userId) {
  return prisma.$transaction((tx) => walletService.getOrCreateWallet(tx, userId));
}

router.get('/balance', asyncHandler(async (req, res) => {
  const wallet = await walletFor(req.user.id);
  const transactions = await prisma.walletTransaction.findMany({
    where: { walletId: wallet.id },
    orderBy: { createdAt: 'desc' },
    take: 25,
  });
  res.json({
    wallet: serializeWallet(wallet),
    currency: 'ILS',
    feeRate: config.platformFeeRate,
    transactions: transactions.map(serializeTransaction),
  });
}));

// Credits the wallet without a payment. Only enabled in mock mode (no Stripe
// key) or when ALLOW_DIRECT_DEPOSIT=true; config.js refuses it in production.
router.post('/deposit', asyncHandler(async (req, res) => {
  if (!config.allowDirectDeposit) {
    throw new HttpError(403, 'Direct deposits are disabled. Use Stripe checkout.', 'DEPOSIT_DISABLED');
  }
  const { amount } = parse(amountSchema, req.body);
  const wallet = await prisma.$transaction(async (tx) => {
    const w = await walletService.getOrCreateWallet(tx, req.user.id);
    await walletService.addFunds(tx, { walletId: w.id, cents: toCents(amount), type: 'deposit', note: 'Direct deposit (test mode)' });
    return tx.wallet.findUnique({ where: { id: w.id } });
  });
  walletService.notifyWallet(wallet);
  res.status(201).json({ wallet: serializeWallet(wallet) });
}));

router.post('/checkout-session', asyncHandler(async (req, res) => {
  const { amount } = parse(amountSchema, req.body);
  if (config.stripe.mockMode) {
    // The frontend falls back to /deposit when it sees mock: true.
    return res.json({ mock: true, url: null });
  }
  const wallet = await walletFor(req.user.id);
  const session = await stripeService.createTopUpSession({ user: req.user, wallet, amount });
  return res.json({ mock: false, id: session.id, url: session.url });
}));

router.get('/checkout-session/:id', asyncHandler(async (req, res) => {
  const result = await stripeService.confirmSession(req.params.id, req.user);
  const wallet = await walletFor(req.user.id);
  res.json({ ...result, wallet: serializeWallet(wallet) });
}));

module.exports = router;
