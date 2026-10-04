const express = require('express');
const { z } = require('zod');
const { prisma } = require('../db');
const { asyncHandler, parse, HttpError } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const jobService = require('../services/jobService');
const { publicUser, serializeProfile, serializeWallet, serializeJob } = require('../serializers');

const router = express.Router();
router.use(authenticate, requireRole('tradesperson'));

router.get('/me', asyncHandler(async (req, res) => {
  const [profile, wallet, activeJob] = await Promise.all([
    prisma.tradespersonProfile.findUnique({ where: { userId: req.user.id } }),
    prisma.wallet.findUnique({ where: { tradespersonId: req.user.id } }),
    jobService.activeJobFor(req.user.id),
  ]);
  res.json({
    user: publicUser(req.user),
    profile: serializeProfile(profile),
    wallet: serializeWallet(wallet),
    activeJob: serializeJob(activeJob, req.user),
  });
}));

// Online / offline toggle. A suspended account can only be reinstated by an admin.
router.post('/me/availability', asyncHandler(async (req, res) => {
  const { online } = parse(z.object({ online: z.boolean() }), req.body);
  const { count } = await prisma.tradespersonProfile.updateMany({
    where: { userId: req.user.id, status: { not: 'suspended' } },
    data: { status: online ? 'active' : 'inactive' },
  });
  if (count === 0) throw new HttpError(403, 'Your account is suspended pending review', 'ACCOUNT_SUSPENDED');
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId: req.user.id } });
  res.json({ profile: serializeProfile(profile) });
}));

module.exports = router;
