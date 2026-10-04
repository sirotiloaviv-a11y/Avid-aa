const express = require('express');
const { z } = require('zod');
const { asyncHandler, parse } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const { PROFILE_STATUSES } = require('../domain/constants');
const adminService = require('../services/adminService');
const { serializeJob, serializeProfile, serializeWallet } = require('../serializers');

const router = express.Router();
router.use(authenticate, requireRole('admin'));

router.get('/flagged-jobs', asyncHandler(async (req, res) => {
  const { state } = parse(z.object({ state: z.enum(['open', 'resolved', 'all']).default('open') }), req.query);
  const { jobs, flagCounts } = await adminService.listFlaggedJobs({ state });
  res.json({
    jobs: jobs.map((job) => ({
      ...serializeJob(job, req.user),
      tradespersonFlagsInWindow: job.tradespersonId ? flagCounts.get(job.tradespersonId) : 0,
    })),
  });
}));

router.post('/flagged-jobs', asyncHandler(async (req, res) => {
  const body = parse(z.object({
    jobId: z.string().min(1),
    action: z.enum(['approve', 'charge_estimate', 'void']),
    note: z.string().trim().max(500).optional(),
  }), req.body);
  const job = await adminService.resolveFlaggedJob(req.user, body);
  res.json({ job: serializeJob(job, req.user) });
}));

router.get('/tradespeople', asyncHandler(async (req, res) => {
  const pros = await adminService.listTradespeople();
  res.json({
    tradespeople: pros.map((pro) => ({
      id: pro.id,
      name: pro.name,
      phone: pro.phone,
      profile: serializeProfile(pro.profile),
      wallet: serializeWallet(pro.wallet),
      flagsInWindow: pro.flagsInWindow,
    })),
  });
}));

router.post('/tradespeople/:userId/status', asyncHandler(async (req, res) => {
  const { status } = parse(z.object({ status: z.enum(PROFILE_STATUSES) }), req.body);
  const profile = await adminService.setTradespersonStatus(req.params.userId, status);
  res.json({ profile: serializeProfile(profile) });
}));

router.post('/wallets/:userId/adjust', asyncHandler(async (req, res) => {
  const body = parse(z.object({
    amount: z.coerce.number().refine((n) => n !== 0, 'Amount must not be zero').refine((n) => Math.abs(n) <= 10000, 'At most ₪10,000 per adjustment'),
    note: z.string().trim().max(300).optional(),
  }), req.body);
  const wallet = await adminService.adjustWallet(req.params.userId, body, req.user);
  res.json({ wallet: serializeWallet(wallet) });
}));

module.exports = router;
