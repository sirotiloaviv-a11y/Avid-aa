const express = require('express');
const config = require('../config');
const { catalog } = require('../domain/pricing');
const { TOP_UP_PRESETS, TOP_UP_MIN, TOP_UP_MAX } = require('../domain/constants');

const router = express.Router();

router.get('/', (req, res) => {
  res.json({
    currency: 'ILS',
    feeRate: config.platformFeeRate,
    services: catalog(),
    topUp: { presets: TOP_UP_PRESETS, min: TOP_UP_MIN, max: TOP_UP_MAX, mockMode: config.stripe.mockMode },
  });
});

module.exports = router;
