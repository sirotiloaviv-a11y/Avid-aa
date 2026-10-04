const { toNumber } = require('./domain/money');

function publicUser(user) {
  if (!user) return null;
  return {
    id: user.id,
    name: user.name,
    phone: user.phone,
    role: user.role,
    latitude: user.latitude,
    longitude: user.longitude,
  };
}

function serializeProfile(profile) {
  if (!profile) return null;
  return {
    userId: profile.userId,
    licenseNumber: profile.licenseNumber,
    serviceType: profile.serviceType,
    status: profile.status,
    fraudScore: profile.fraudScore,
    rating: profile.rating ?? 0,
    ratingCount: profile.ratingCount ?? 0,
  };
}

function serializeWallet(wallet) {
  if (!wallet) return null;
  return {
    id: wallet.id,
    tradespersonId: wallet.tradespersonId,
    balance: toNumber(wallet.balance),
    lockedBalance: toNumber(wallet.lockedBalance),
  };
}

function serializeTransaction(tx) {
  return {
    id: tx.id,
    amount: toNumber(tx.amount),
    type: tx.type,
    jobId: tx.jobId,
    note: tx.note,
    createdAt: tx.createdAt,
  };
}

// What a viewer may see of a job:
// - the completion code only ever goes to the client who booked it (and
//   admins); the tradesperson must get it from the client in person;
// - the client's phone goes to the assigned tradesperson only.
function serializeJob(job, viewer) {
  if (!job) return null;
  const isClient = viewer && viewer.id === job.clientId;
  const isAdmin = viewer && viewer.role === 'admin';
  const isAssignedPro = viewer && job.tradespersonId && viewer.id === job.tradespersonId;

  const out = {
    id: job.id,
    clientId: job.clientId,
    tradespersonId: job.tradespersonId,
    serviceType: job.serviceType,
    description: job.description,
    address: job.address,
    latitude: job.latitude,
    longitude: job.longitude,
    estimatedPrice: toNumber(job.estimatedPrice),
    finalPrice: toNumber(job.finalPrice),
    platformFee: toNumber(job.platformFee),
    status: job.status,
    flaggedAt: job.flaggedAt,
    flagReason: job.flagReason,
    resolution: job.resolution,
    resolutionNote: job.resolutionNote,
    resolvedAt: job.resolvedAt,
    assignedAt: job.assignedAt,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    cancelledAt: job.cancelledAt,
    createdAt: job.createdAt,
    photos: Array.isArray(job.photos) ? job.photos.map((p) => p.url) : [],
    review: job.review ? { rating: job.review.rating, comment: job.review.comment, createdAt: job.review.createdAt } : null,
  };

  if (isClient || isAdmin) out.completionCode = job.completionCode;
  if (isAdmin) out.codeAttempts = job.codeAttempts;

  if (job.client) {
    out.client = { id: job.client.id, name: job.client.name };
    if (isAssignedPro || isAdmin) out.client.phone = job.client.phone;
  }
  if (job.tradesperson) {
    out.tradesperson = {
      id: job.tradesperson.id,
      name: job.tradesperson.name,
      phone: isClient || isAdmin || isAssignedPro ? job.tradesperson.phone : undefined,
      latitude: job.tradesperson.latitude,
      longitude: job.tradesperson.longitude,
    };
    if (job.tradesperson.profile) {
      out.tradesperson.licenseNumber = job.tradesperson.profile.licenseNumber;
      out.tradesperson.serviceType = job.tradesperson.profile.serviceType;
      out.tradesperson.rating = job.tradesperson.profile.rating ?? 0;
      out.tradesperson.ratingCount = job.tradesperson.profile.ratingCount ?? 0;
      if (isAdmin) {
        out.tradesperson.status = job.tradesperson.profile.status;
        out.tradesperson.fraudScore = job.tradesperson.profile.fraudScore;
      }
    }
    if (isAdmin && job.tradesperson.wallet) {
      out.tradesperson.wallet = serializeWallet(job.tradesperson.wallet);
    }
  }
  return out;
}

module.exports = { publicUser, serializeProfile, serializeWallet, serializeTransaction, serializeJob };
