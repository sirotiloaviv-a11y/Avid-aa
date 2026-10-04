const express = require('express');
const { z } = require('zod');
const { prisma } = require('../db');
const { asyncHandler, parse } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const { limits } = require('../middleware/rateLimit');
const { SERVICE_TYPES } = require('../domain/constants');
const jobService = require('../services/jobService');
const { serializeJob } = require('../serializers');

const router = express.Router();
router.use(authenticate);

const latitude = z.coerce.number().min(-90).max(90);
const longitude = z.coerce.number().min(-180).max(180);

const createSchema = z.object({
  serviceType: z.enum(SERVICE_TYPES),
  description: z.string().trim().min(5, 'Describe the problem in a few words').max(1000),
  latitude,
  longitude,
  address: z.string().trim().max(200).optional(),
});

router.post('/create', requireRole('client'), limits.createJob, asyncHandler(async (req, res) => {
  const body = parse(createSchema, req.body);
  const job = await jobService.createJob(req.user, body);
  res.status(201).json({ job: serializeJob(job, req.user) });
}));

router.get('/mine', asyncHandler(async (req, res) => {
  const jobs = await jobService.listMine(req.user);
  res.json({ jobs: jobs.map((job) => serializeJob(job, req.user)) });
}));

router.get('/nearby', requireRole('tradesperson'), asyncHandler(async (req, res) => {
  const query = parse(z.object({
    lat: latitude.optional(),
    lng: longitude.optional(),
    radiusKm: z.coerce.number().positive().max(100).optional(),
  }), req.query);
  const jobs = await jobService.nearbyJobs(req.user, query);
  res.json({ jobs });
}));

router.get('/:id', asyncHandler(async (req, res) => {
  const job = await jobService.loadJob(prisma, req.params.id);
  jobService.assertParticipant(job, req.user);
  res.json({ job: serializeJob(job, req.user) });
}));

router.post('/:id/accept', requireRole('tradesperson'), asyncHandler(async (req, res) => {
  const body = parse(z.object({ latitude: latitude.optional(), longitude: longitude.optional() }), req.body || {});
  const location = body.latitude != null && body.longitude != null ? body : null;
  const job = await jobService.acceptJob(req.user, req.params.id, location);
  res.json({ job: serializeJob(job, req.user) });
}));

router.post('/:id/start', requireRole('tradesperson'), asyncHandler(async (req, res) => {
  const job = await jobService.startJob(req.user, req.params.id);
  res.json({ job: serializeJob(job, req.user) });
}));

router.post('/:id/verify-and-complete', requireRole('tradesperson'), limits.completeJob, asyncHandler(async (req, res) => {
  const body = parse(z.object({
    completionCode: z.string().trim().regex(/^\d{4}$/, 'The code is 4 digits'),
    finalPrice: z.coerce.number().positive().max(100000),
  }), req.body);
  const result = await jobService.verifyAndComplete(req.user, req.params.id, body);
  res.json({
    outcome: result.outcome,
    suspended: result.suspended,
    job: serializeJob(result.job, req.user),
  });
}));

router.post('/:id/cancel', asyncHandler(async (req, res) => {
  const { reason } = parse(z.object({ reason: z.string().trim().max(300).optional() }), req.body || {});
  const job = await jobService.cancelJob(req.user, req.params.id, reason);
  res.json({ job: serializeJob(job, req.user) });
}));

module.exports = router;
