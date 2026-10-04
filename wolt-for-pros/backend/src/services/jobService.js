const crypto = require('crypto');
const config = require('../config');
const { prisma } = require('../db');
const { HttpError } = require('../middleware/errors');
const { toCents, fromCents } = require('../domain/money');
const { estimateFor, feeCents, generateCompletionCode } = require('../domain/pricing');
const { isUnderpriced, underpriceReason } = require('../domain/fraud');
const { haversineKm, etaMinutes } = require('../domain/geo');
const { ACTIVE_JOB_STATUSES, MAX_CODE_ATTEMPTS, DEFAULT_RADAR_RADIUS_KM } = require('../domain/constants');
const walletService = require('./walletService');
const fraudService = require('./fraudService');
const locationStore = require('./locationStore');
const realtime = require('../realtime');
const { serializeJob } = require('../serializers');

const jobInclude = {
  client: true,
  tradesperson: { include: { profile: true } },
};

const adminJobInclude = {
  client: true,
  tradesperson: { include: { profile: true, wallet: true } },
};

function feeFor(priceCents) {
  return feeCents(priceCents, config.platformFeeRate);
}

async function loadJob(client, jobId, include = jobInclude) {
  const args = { where: { id: jobId } };
  if (include) args.include = include;
  const job = await client.job.findUnique(args);
  if (!job) throw new HttpError(404, 'Job not found', 'JOB_NOT_FOUND');
  return job;
}

function assertParticipant(job, user) {
  if (user.role === 'admin') return;
  if (job.clientId === user.id) return;
  if (job.tradespersonId && job.tradespersonId === user.id) return;
  throw new HttpError(403, 'You are not part of this job', 'FORBIDDEN');
}

// Push the change to everyone watching the job, plus the people involved.
// Payloads are serialized without a viewer, so they never carry the
// completion code; clients refetch the job when they need it.
function broadcastJob(job) {
  const payload = serializeJob(job, null);
  realtime.toJob(job.id, 'job:updated', payload);
  realtime.toUser(job.clientId, 'job:updated', payload);
  if (job.tradespersonId) realtime.toUser(job.tradespersonId, 'job:updated', payload);
}

async function getProfile(userId) {
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId } });
  if (!profile) throw new HttpError(403, 'Tradesperson profile not found', 'NO_PROFILE');
  return profile;
}

async function createJob(clientUser, { serviceType, description, latitude, longitude, address }) {
  const { estimate } = estimateFor(serviceType);
  const job = await prisma.job.create({
    data: {
      clientId: clientUser.id,
      serviceType,
      description,
      address: address || null,
      latitude,
      longitude,
      estimatedPrice: fromCents(estimate * 100),
      completionCode: generateCompletionCode(crypto.randomInt),
      status: 'requested',
    },
    include: jobInclude,
  });
  await prisma.user.update({ where: { id: clientUser.id }, data: { latitude, longitude } });

  const estimateCents = toCents(job.estimatedPrice);
  realtime.toPros(job.serviceType, 'job:new', {
    ...serializeJob(job, null),
    feeAmount: feeFor(estimateCents) / 100,
    payoutEstimate: (estimateCents - feeFor(estimateCents)) / 100,
  });
  return job;
}

async function listMine(user) {
  const where = user.role === 'tradesperson' ? { tradespersonId: user.id } : { clientId: user.id };
  return prisma.job.findMany({ where, include: jobInclude, orderBy: { createdAt: 'desc' }, take: 50 });
}

async function activeJobFor(tradespersonId) {
  return prisma.job.findFirst({
    where: { tradespersonId, status: { in: ACTIVE_JOB_STATUSES } },
    include: jobInclude,
    orderBy: { assignedAt: 'desc' },
  });
}

async function nearbyJobs(proUser, { lat, lng, radiusKm = DEFAULT_RADAR_RADIUS_KM }) {
  const profile = await getProfile(proUser.id);
  const origin = Number.isFinite(lat) && Number.isFinite(lng)
    ? { lat, lng }
    : proUser.latitude != null && proUser.longitude != null
      ? { lat: proUser.latitude, lng: proUser.longitude }
      : null;

  const [jobs, wallet] = await Promise.all([
    prisma.job.findMany({
      where: { status: 'requested', serviceType: profile.serviceType },
      include: { client: true },
      orderBy: { createdAt: 'desc' },
      take: 200,
    }),
    prisma.wallet.findUnique({ where: { tradespersonId: proUser.id } }),
  ]);
  const availableCents = wallet ? toCents(wallet.balance) : 0;

  return jobs
    .map((job) => {
      const estimateCents = toCents(job.estimatedPrice);
      const fee = feeFor(estimateCents);
      const distanceKm = origin ? haversineKm(origin, { lat: job.latitude, lng: job.longitude }) : null;
      return {
        ...serializeJob(job, proUser),
        distanceKm: distanceKm == null ? null : Math.round(distanceKm * 10) / 10,
        etaMinutes: distanceKm == null ? null : etaMinutes(distanceKm),
        feeAmount: fee / 100,
        payoutEstimate: (estimateCents - fee) / 100,
        canAfford: availableCents >= fee,
      };
    })
    .filter((job) => job.distanceKm == null || job.distanceKm <= radiusKm)
    .sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity));
}

async function acceptJob(proUser, jobId, location) {
  const profile = await getProfile(proUser.id);
  if (profile.status === 'suspended') {
    throw new HttpError(403, 'Your account is suspended pending review. Contact support.', 'ACCOUNT_SUSPENDED');
  }
  if (profile.status !== 'active') {
    throw new HttpError(409, 'Go online before accepting jobs', 'NOT_ONLINE');
  }

  const job = await prisma.$transaction(async (tx) => {
    const current = await loadJob(tx, jobId, null);
    if (current.serviceType !== profile.serviceType) {
      throw new HttpError(403, `This job needs a ${current.serviceType}`, 'WRONG_SERVICE_TYPE');
    }
    if (current.status !== 'requested') {
      throw new HttpError(409, 'This job is no longer available', 'JOB_NOT_AVAILABLE');
    }
    const busy = await tx.job.count({
      where: { tradespersonId: proUser.id, status: { in: ACTIVE_JOB_STATUSES } },
    });
    if (busy > 0) throw new HttpError(409, 'Finish your current job before accepting another', 'ALREADY_ON_JOB');

    const fee = feeFor(toCents(current.estimatedPrice));
    const wallet = await walletService.getOrCreateWallet(tx, proUser.id);
    await walletService.holdFee(tx, { walletId: wallet.id, cents: fee, jobId });

    // Guarded on status so two tradespeople racing for the same job cannot
    // both win; the loser's transaction (and fee hold) rolls back.
    const { count } = await tx.job.updateMany({
      where: { id: jobId, status: 'requested' },
      data: { status: 'assigned', tradespersonId: proUser.id, platformFee: fromCents(fee), assignedAt: new Date() },
    });
    if (count === 0) throw new HttpError(409, 'Another tradesperson just took this job', 'JOB_NOT_AVAILABLE');

    if (location) {
      await tx.user.update({ where: { id: proUser.id }, data: { latitude: location.latitude, longitude: location.longitude } });
    }
    return loadJob(tx, jobId);
  });

  if (location) locationStore.set(proUser.id, { lat: location.latitude, lng: location.longitude });
  realtime.toPros(job.serviceType, 'job:taken', { id: job.id });
  broadcastJob(job);
  await notifyWalletOf(proUser.id);
  return job;
}

async function startJob(proUser, jobId) {
  const job = await loadJob(prisma, jobId, null);
  if (job.tradespersonId !== proUser.id) throw new HttpError(403, 'This is not your job', 'FORBIDDEN');
  const { count } = await prisma.job.updateMany({
    where: { id: jobId, tradespersonId: proUser.id, status: 'assigned' },
    data: { status: 'in_progress', startedAt: new Date() },
  });
  if (count === 0) throw new HttpError(409, `Cannot start a job that is ${job.status}`, 'INVALID_STATUS');
  const updated = await loadJob(prisma, jobId);
  broadcastJob(updated);
  return updated;
}

function codesMatch(expected, given) {
  const a = Buffer.from(String(expected));
  const b = Buffer.from(String(given));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

async function verifyAndComplete(proUser, jobId, { completionCode, finalPrice }) {
  const job = await loadJob(prisma, jobId, null);
  if (job.tradespersonId !== proUser.id) throw new HttpError(403, 'This is not your job', 'FORBIDDEN');
  if (!ACTIVE_JOB_STATUSES.includes(job.status)) {
    throw new HttpError(409, `Cannot complete a job that is ${job.status}`, 'INVALID_STATUS');
  }
  if (job.codeAttempts >= MAX_CODE_ATTEMPTS) {
    throw new HttpError(423, 'Too many wrong codes. This job is locked; contact support.', 'CODE_LOCKED');
  }

  // Wrong guesses are recorded outside the settlement transaction so the
  // counter survives the rejection. The guard keeps concurrent guesses from
  // going past the limit.
  if (!codesMatch(job.completionCode, completionCode)) {
    const { count } = await prisma.job.updateMany({
      where: { id: jobId, codeAttempts: { lt: MAX_CODE_ATTEMPTS } },
      data: { codeAttempts: { increment: 1 } },
    });
    const remaining = Math.max(0, MAX_CODE_ATTEMPTS - job.codeAttempts - (count > 0 ? 1 : 0));
    throw new HttpError(400, `Incorrect completion code. ${remaining} attempt(s) left.`, 'WRONG_CODE', { remaining });
  }

  const estimateCents = toCents(job.estimatedPrice);
  const finalCents = toCents(finalPrice);
  const heldCents = toCents(job.platformFee);
  const now = new Date();
  const flagged = isUnderpriced(estimateCents, finalCents);

  const result = await prisma.$transaction(async (tx) => {
    const wallet = await walletService.getOrCreateWallet(tx, proUser.id);

    if (flagged) {
      // The hold stays locked until an admin resolves the dispute.
      const { count } = await tx.job.updateMany({
        where: { id: jobId, status: { in: ACTIVE_JOB_STATUSES } },
        data: {
          status: 'flagged',
          finalPrice: fromCents(finalCents),
          flaggedAt: now,
          flagReason: underpriceReason(estimateCents, finalCents),
          completedAt: now,
        },
      });
      if (count === 0) throw new HttpError(409, 'Job changed while completing; refresh and retry', 'CONFLICT');
      const fraud = await fraudService.recordFlag(tx, proUser.id, now);
      return { outcome: 'flagged', ...fraud };
    }

    const finalFee = feeFor(finalCents);
    const { count } = await tx.job.updateMany({
      where: { id: jobId, status: { in: ACTIVE_JOB_STATUSES } },
      data: { status: 'completed', finalPrice: fromCents(finalCents), platformFee: fromCents(finalFee), completedAt: now },
    });
    if (count === 0) throw new HttpError(409, 'Job changed while completing; refresh and retry', 'CONFLICT');
    await walletService.settleFee(tx, { walletId: wallet.id, heldCents, finalFeeCents: finalFee, jobId });
    return { outcome: 'completed', suspended: false };
  });

  const updated = await loadJob(prisma, jobId);
  broadcastJob(updated);
  await notifyWalletOf(proUser.id);
  if (result.outcome === 'flagged') {
    realtime.toAdmins('flagged:new', serializeJob(updated, { role: 'admin' }));
  }
  return { job: updated, ...result };
}

async function cancelJob(user, jobId, reason) {
  const current = await loadJob(prisma, jobId, null);
  assertParticipant(current, user);

  const isClient = current.clientId === user.id;
  const isPro = current.tradespersonId === user.id;
  const isAdmin = user.role === 'admin';

  let allowedFrom;
  let releaseToPool = false;
  if (isAdmin) allowedFrom = ['requested', 'assigned', 'in_progress'];
  else if (isClient) allowedFrom = ['requested', 'assigned'];
  else if (isPro) {
    // A tradesperson backing out puts the job back on the radar.
    allowedFrom = ['assigned'];
    releaseToPool = true;
  }
  if (!allowedFrom.includes(current.status)) {
    throw new HttpError(409, `A ${current.status} job cannot be cancelled by you`, 'INVALID_STATUS');
  }

  const previousProId = current.tradespersonId;
  const job = await prisma.$transaction(async (tx) => {
    const data = releaseToPool
      ? { status: 'requested', tradespersonId: null, platformFee: null, assignedAt: null }
      : { status: 'cancelled', cancelledAt: new Date() };
    const { count } = await tx.job.updateMany({ where: { id: jobId, status: current.status }, data });
    if (count === 0) throw new HttpError(409, 'Job changed while cancelling; refresh and retry', 'CONFLICT');

    if (previousProId && current.platformFee != null) {
      const wallet = await walletService.getOrCreateWallet(tx, previousProId);
      const who = isAdmin && !isClient ? 'admin' : isClient ? 'client' : 'tradesperson';
      await walletService.releaseHold(tx, {
        walletId: wallet.id,
        cents: toCents(current.platformFee),
        jobId,
        note: `Job cancelled by ${who}${reason ? `: ${reason}` : ''}`,
      });
    }
    return loadJob(tx, jobId);
  });

  broadcastJob(job);
  if (previousProId) {
    realtime.toUser(previousProId, 'job:updated', serializeJob(job, null));
    await notifyWalletOf(previousProId);
  }
  if (releaseToPool) {
    const estimateCents = toCents(job.estimatedPrice);
    realtime.toPros(job.serviceType, 'job:new', {
      ...serializeJob(job, null),
      feeAmount: feeFor(estimateCents) / 100,
      payoutEstimate: (estimateCents - feeFor(estimateCents)) / 100,
    });
  } else {
    realtime.toPros(job.serviceType, 'job:taken', { id: job.id });
  }
  return job;
}

async function notifyWalletOf(tradespersonId) {
  const wallet = await prisma.wallet.findUnique({ where: { tradespersonId } });
  if (wallet) walletService.notifyWallet(wallet);
}

module.exports = {
  jobInclude,
  adminJobInclude,
  feeFor,
  loadJob,
  assertParticipant,
  broadcastJob,
  notifyWalletOf,
  createJob,
  listMine,
  activeJobFor,
  nearbyJobs,
  acceptJob,
  startJob,
  verifyAndComplete,
  cancelJob,
};
