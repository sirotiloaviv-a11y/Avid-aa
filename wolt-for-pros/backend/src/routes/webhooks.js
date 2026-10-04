const express = require('express');
const { asyncHandler } = require('../middleware/errors');
const stripeService = require('../services/stripeService');

const router = express.Router();

// Mounted before express.json(): signature verification needs the raw bytes.
router.post('/stripe', express.raw({ type: 'application/json' }), asyncHandler(async (req, res) => {
  const event = stripeService.constructWebhookEvent(req.body, req.headers['stripe-signature']);
  const result = await stripeService.handleWebhookEvent(event);
  res.json({ received: true, ...result });
}));

module.exports = router;
