const express = require('express');
const { asyncHandler, HttpError } = require('../middleware/errors');
const { authenticate, requireRole } = require('../middleware/auth');
const { limits } = require('../middleware/rateLimit');
const { MAX_UPLOAD_BYTES } = require('../domain/constants');
const storageService = require('../services/storageService');

const router = express.Router();

// POST /api/uploads with the image as the raw body and its Content-Type
// (image/jpeg, image/png or image/webp). Returns { url } to pass in a job's
// `photos`. The type is verified from the file's bytes.
router.post(
  '/',
  authenticate,
  requireRole('client'),
  limits.upload,
  express.raw({ type: ['image/jpeg', 'image/png', 'image/webp'], limit: MAX_UPLOAD_BYTES }),
  asyncHandler(async (req, res) => {
    // express.raw leaves other content types unparsed.
    if (!Buffer.isBuffer(req.body)) {
      throw new HttpError(415, 'Send a JPEG, PNG or WebP image with its Content-Type', 'UNSUPPORTED_IMAGE');
    }
    const saved = await storageService.saveImage(req.body);
    res.status(201).json({ url: saved.url });
  }),
);

module.exports = router;
