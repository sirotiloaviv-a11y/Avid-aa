const { prisma } = require('../db');
const { HttpError } = require('../middleware/errors');
const { fromCents } = require('../domain/money');
const { settlement } = require('../domain/pricing');
const realtime = require('../realtime');
const { serializeWallet } = require('../serializers');

// Every function taking `tx` must run inside a prisma.$transaction so the
// balance change and its ledger row commit (or roll back) together. Balance
// guards are conditional updateMany calls, so two concurrent holds can never
// both spend the same shekel.

async function getOrCreateWallet(tx, tradespersonId) {
  return tx.wallet.upsert({
    where: { tradespersonId },
    update: {},
    create: { tradespersonId },
  });
}

async function addFunds(tx, { walletId, cents, type, jobId = null, externalRef = null, note = null }) {
  const amount = fromCents(cents);
  await tx.wallet.update({ where: { id: walletId }, data: { balance: { increment: amount } } });
  return tx.walletTransaction.create({ data: { walletId, amount, type, jobId, externalRef, note } });
}

async function holdFee(tx, { walletId, cents, jobId }) {
  const amount = fromCents(cents);
  const { count } = await tx.wallet.updateMany({
    where: { id: walletId, balance: { gte: amount } },
    data: { balance: { decrement: amount }, lockedBalance: { increment: amount } },
  });
  if (count === 0) {
    throw new HttpError(402, 'Your available balance does not cover the platform fee for this job. Top up your wallet to accept it.', 'INSUFFICIENT_BALANCE', { requiredFee: cents / 100 });
  }
  await tx.walletTransaction.create({
    data: { walletId, amount: fromCents(-cents), type: 'fee_hold', jobId, note: 'Platform fee held on job acceptance' },
  });
}

async function releaseHold(tx, { walletId, cents, jobId, note = null }) {
  if (!cents || cents <= 0) return;
  const amount = fromCents(cents);
  const { count } = await tx.wallet.updateMany({
    where: { id: walletId, lockedBalance: { gte: amount } },
    data: { lockedBalance: { decrement: amount }, balance: { increment: amount } },
  });
  if (count === 0) throw new Error(`Wallet ${walletId} locked balance is below the ${amount} hold for job ${jobId}`);
  await tx.walletTransaction.create({
    data: { walletId, amount, type: 'refund', jobId, note: note || 'Held fee released' },
  });
}

async function settleFee(tx, { walletId, heldCents, finalFeeCents, jobId, note = null }) {
  const s = settlement(heldCents, finalFeeCents);
  const { count } = await tx.wallet.updateMany({
    where: { id: walletId, lockedBalance: { gte: fromCents(heldCents) } },
    data: {
      lockedBalance: { increment: fromCents(s.lockedDelta) },
      balance: { increment: fromCents(s.availableDelta) },
    },
  });
  if (count === 0) throw new Error(`Wallet ${walletId} locked balance is below the hold for job ${jobId}`);
  await tx.walletTransaction.create({
    data: { walletId, amount: fromCents(-s.chargedCents), type: 'fee_deduction', jobId, note: note || 'Platform fee charged' },
  });
  if (s.releasedCents > 0) {
    await tx.walletTransaction.create({
      data: { walletId, amount: fromCents(s.releasedCents), type: 'refund', jobId, note: 'Unused part of the held fee released' },
    });
  }
  return s;
}

// Idempotent on the Stripe Checkout Session id: the webhook and the
// post-redirect confirmation can both call this for the same payment.
async function creditStripeDeposit({ walletId, cents, sessionId }) {
  try {
    const result = await prisma.$transaction(async (tx) => {
      const existing = await tx.walletTransaction.findUnique({ where: { externalRef: sessionId } });
      if (existing) return { credited: false, wallet: await tx.wallet.findUnique({ where: { id: walletId } }) };
      await addFunds(tx, { walletId, cents, type: 'deposit', externalRef: sessionId, note: 'Stripe top-up' });
      return { credited: true, wallet: await tx.wallet.findUnique({ where: { id: walletId } }) };
    });
    if (result.credited && result.wallet) notifyWallet(result.wallet);
    return result;
  } catch (err) {
    // A concurrent call won the race on the unique external_ref.
    if (err && err.code === 'P2002') return { credited: false };
    throw err;
  }
}

function notifyWallet(wallet) {
  realtime.toUser(wallet.tradespersonId, 'wallet:updated', serializeWallet(wallet));
}

module.exports = {
  getOrCreateWallet,
  addFunds,
  holdFee,
  releaseHold,
  settleFee,
  creditStripeDeposit,
  notifyWallet,
};
