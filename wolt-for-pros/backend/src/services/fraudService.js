const { flagWindowStart, shouldSuspend } = require('../domain/fraud');

// Flags count toward suspension unless an admin later ruled the job legitimate.
function countableFlagsWhere(tradespersonId, now) {
  return {
    tradespersonId,
    flaggedAt: { gte: flagWindowStart(now) },
    OR: [{ resolution: null }, { resolution: { not: 'approved' } }],
  };
}

// Call inside the transaction that flags the job (after the job row is
// updated) so the count includes it.
async function recordFlag(tx, tradespersonId, now = new Date()) {
  await tx.tradespersonProfile.update({
    where: { userId: tradespersonId },
    data: { fraudScore: { increment: 1 } },
  });
  const flagsInWindow = await tx.job.count({ where: countableFlagsWhere(tradespersonId, now) });
  let suspended = false;
  if (shouldSuspend(flagsInWindow)) {
    const { count } = await tx.tradespersonProfile.updateMany({
      where: { userId: tradespersonId, status: { not: 'suspended' } },
      data: { status: 'suspended' },
    });
    suspended = count > 0;
  }
  return { flagsInWindow, suspended };
}

async function clearFlag(tx, tradespersonId) {
  await tx.tradespersonProfile.updateMany({
    where: { userId: tradespersonId, fraudScore: { gt: 0 } },
    data: { fraudScore: { decrement: 1 } },
  });
}

async function flagsInWindow(client, tradespersonId, now = new Date()) {
  return client.job.count({ where: countableFlagsWhere(tradespersonId, now) });
}

module.exports = { recordFlag, clearFlag, flagsInWindow };
