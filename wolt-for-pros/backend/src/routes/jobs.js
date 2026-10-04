const express = require('express');
const { z } = require('zod');
const { prisma } = require('../db');
const { asyncHandler, parse } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const { limits } = require('../middleware/rateLimit');
const { SERVICE_TYPES, MAX_JOB_PHOTOS, MAX_MESSAGE_LENGTH } = require('../domain/constants');
const { isAllowedPhotoUrl } = require('../domain/media');
const jobService = require('../services/jobService');
const reviewService = require('../services/reviewService');
const messageService = require('../services/messageService');
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
  photos: z.array(z.string().trim().refine(isAllowedPhotoUrl, 'Use an uploaded photo or an https image URL'))
    .max(MAX_JOB_PHOTOS, `Up to ${MAX_JOB_PHOTOS} photos`)
    .default([]),
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

router.post('/:id/review', requireRole('client'), asyncHandler(async (req, res) => {
  const body = parse(z.object({
    rating: z.coerce.number().int().min(1, 'Rate from 1 to 5 stars').max(5, 'Rate from 1 to 5 stars'),
    comment: z.string().trim().max(1000).optional(),
  }), req.body);
  const { review, profile } = await reviewService.createReview(req.user, req.params.id, body);
  res.status(201).json({
    review: reviewService.serializeReview(review),
    tradesperson: { rating: profile.rating, ratingCount: profile.ratingCount },
  });
}));

router.get('/:id/messages', asyncHandler(async (req, res) => {
  const messages = await messageService.listMessages(req.user, req.params.id);
  res.json({ messages });
}));

// REST twin of the socket's send_message, for clients without a socket.
router.post('/:id/messages', limits.message, asyncHandler(async (req, res) => {
  const { body } = parse(z.object({ body: z.string().trim().min(1).max(MAX_MESSAGE_LENGTH) }), req.body);
  const message = await messageService.sendMessage(req.user, req.params.id, body);
  res.status(201).json({ message });
}));

router.post('/:id/cancel', asyncHandler(async (req, res) => {
  const { reason } = parse(z.object({ reason: z.string().trim().max(300).optional() }), req.body || {});
  const job = await jobService.cancelJob(req.user, req.params.id, reason);
  res.json({ job: serializeJob(job, req.user) });
}));

module.exports = router;
