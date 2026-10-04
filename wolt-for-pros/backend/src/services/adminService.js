const config = require('../config');
const { prisma } = require('../db');
const { HttpError } = require('../middleware/errors');
const { toCents } = require('../domain/money');
const { feeCents } = require('../domain/pricing');
const walletService = require('./walletService');
const fraudService = require('./fraudService');
const jobService = require('./jobService');
const realtime = require('../realtime');

async function listFlaggedJobs({ state }) {
  const where = state === 'resolved'
    ? { flaggedAt: { not: null }, resolution: { not: null } }
    : state === 'all'
      ? { flaggedAt: { not: null } }
      : { status: 'flagged' };
  const jobs = await prisma.job.findMany({
    where,
    include: jobService.adminJobInclude,
    orderBy: { flaggedAt: 'desc' },
    take: 200,
  });
  const now = new Date();
  const flagCounts = new Map();
  for (const job of jobs) {
    if (job.tradespersonId && !flagCounts.has(job.tradespersonId)) {
      flagCounts.set(job.tradespersonId, await fraudService.flagsInWindow(prisma, job.tradespersonId, now));
    }
  }
  return { jobs, flagCounts };
}

// Resolution actions for a flagged job, whose fee is still held:
// - approve:          the low price was legitimate; charge the fee on the final price
// - charge_estimate:  treat it as a side deal; charge the fee on the estimate
// - void:             the job did not really happen; release the hold, cancel the job
async function resolveFlaggedJob(adminUser, { jobId, action, note = null }) {
  const current = await jobService.loadJob(prisma, jobId, null);
  if (current.status !== 'flagged') {
    throw new HttpError(409, `Job is ${current.status}, not flagged`, 'INVALID_STATUS');
  }
  if (!current.tradespersonId) throw new Error(`Flagged job ${jobId} has no tradesperson`);
  const heldCents = current.platformFee == null ? 0 : toCents(current.platformFee);
  const now = new Date();
  const resolutionNote = note ? `${note} (by ${adminUser.name})` : `Resolved by ${adminUser.name}`;

  await prisma.$transaction(async (tx) => {
    const wallet = await walletService.getOrCreateWallet(tx, current.tradespersonId);
    let data;
    if (action === 'void') {
      await walletService.releaseHold(tx, { walletId: wallet.id, cents: heldCents, jobId, note: 'Flagged job voided by admin' });
      data = { status: 'cancelled', cancelledAt: now, resolution: 'voided' };
    } else {
      const basis = action === 'approve' ? current.finalPrice : current.estimatedPrice;
      const fee = feeCents(toCents(basis), config.platformFeeRate);
      await walletService.settleFee(tx, {
        walletId: wallet.id,
        heldCents,
        finalFeeCents: fee,
        jobId,
        note: action === 'approve' ? 'Fee on final price (dispute approved)' : 'Fee on estimated price (dispute upheld)',
      });
      data = {
        status: 'completed',
        platformFee: (fee / 100).toFixed(2),
        resolution: action === 'approve' ? 'approved' : 'charged_estimate',
      };
      if (action === 'approve') await fraudService.clearFlag(tx, current.tradespersonId);
    }
    const { count } = await tx.job.updateMany({
      where: { id: jobId, status: 'flagged' },
      data: { ...data, resolutionNote, resolvedAt: now },
    });
    if (count === 0) throw new HttpError(409, 'Job was resolved by someone else', 'CONFLICT');
  });

  const job = await jobService.loadJob(prisma, jobId, jobService.adminJobInclude);
  jobService.broadcastJob(job);
  await jobService.notifyWalletOf(current.tradespersonId);
  return job;
}

async function listTradespeople() {
  const pros = await prisma.user.findMany({
    where: { role: 'tradesperson' },
    include: { profile: true, wallet: true },
    orderBy: { name: 'asc' },
  });
  const now = new Date();
  return Promise.all(pros.map(async (pro) => ({
    ...pro,
    flagsInWindow: await fraudService.flagsInWindow(prisma, pro.id, now),
  })));
}

async function setTradespersonStatus(userId, status) {
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId } });
  if (!profile) throw new HttpError(404, 'Tradesperson not found', 'NOT_FOUND');
  const updated = await prisma.tradespersonProfile.update({ where: { userId }, data: { status } });
  realtime.toUser(userId, 'profile:updated', { status: updated.status });
  return updated;
}

async function adjustWallet(userId, { amount, note }, adminUser) {
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId } });
  if (!profile) throw new HttpError(404, 'Tradesperson not found', 'NOT_FOUND');
  const cents = toCents(amount);
  if (cents === 0) throw new HttpError(400, 'Amount must not be zero', 'VALIDATION_ERROR');
  const wallet = await prisma.$transaction(async (tx) => {
    const w = await walletService.getOrCreateWallet(tx, userId);
    await walletService.addFunds(tx, {
      walletId: w.id,
      cents,
      type: 'adjustment',
      note: `${note || 'Manual adjustment'} (by ${adminUser.name})`,
    });
    return tx.wallet.findUnique({ where: { id: w.id } });
  });
  walletService.notifyWallet(wallet);
  return wallet;
}

module.exports = { listFlaggedJobs, resolveFlaggedJob, listTradespeople, setTradespersonStatus, adjustWallet };
