const { prisma } = require('../db');
const { HttpError } = require('../middleware/errors');
const realtime = require('../realtime');

function serializeReview(review) {
  return review && {
    id: review.id,
    jobId: review.jobId,
    rating: review.rating,
    comment: review.comment,
    createdAt: review.createdAt,
  };
}

// The client of a completed job rates its tradesperson once. The average is
// recomputed from all reviews in the same transaction, so it cannot drift.
async function createReview(clientUser, jobId, { rating, comment = null }) {
  const job = await prisma.job.findUnique({ where: { id: jobId } });
  if (!job) throw new HttpError(404, 'Job not found', 'JOB_NOT_FOUND');
  if (job.clientId !== clientUser.id) throw new HttpError(403, 'Only the client who booked this job can rate it', 'FORBIDDEN');
  if (job.status !== 'completed' || !job.tradespersonId) {
    throw new HttpError(409, 'You can rate a job once it is completed', 'NOT_COMPLETED');
  }

  const { review, profile } = await prisma.$transaction(async (tx) => {
    const existing = await tx.review.findUnique({ where: { jobId } });
    if (existing) throw new HttpError(409, 'You already rated this job', 'ALREADY_REVIEWED');
    const created = await tx.review.create({
      data: { jobId, clientId: clientUser.id, tradespersonId: job.tradespersonId, rating, comment: comment || null },
    });
    const stats = await tx.review.aggregate({
      where: { tradespersonId: job.tradespersonId },
      _avg: { rating: true },
      _count: { _all: true },
    });
    const updated = await tx.tradespersonProfile.update({
      where: { userId: job.tradespersonId },
      data: {
        rating: Math.round((stats._avg.rating || 0) * 100) / 100,
        ratingCount: stats._count._all,
      },
    });
    return { review: created, profile: updated };
  });

  realtime.toUser(job.tradespersonId, 'review:new', {
    review: serializeReview(review),
    rating: profile.rating,
    ratingCount: profile.ratingCount,
  });
  return { review, profile };
}

module.exports = { createReview, serializeReview };
