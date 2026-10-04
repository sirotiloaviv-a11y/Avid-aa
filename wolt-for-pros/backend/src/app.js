const express = require('express');
const cors = require('cors');
const config = require('./config');
const { notFound, errorHandler } = require('./middleware/errors');
const { securityHeaders } = require('./middleware/security');
const { limits } = require('./middleware/rateLimit');

const app = express();
app.disable('x-powered-by');
if (config.trustProxy) app.set('trust proxy', config.trustProxy);
app.use(securityHeaders);
app.use(cors({ origin: config.frontendUrl }));

// Stripe webhooks need the raw body, so they go before the JSON parser.
app.use('/api/webhooks', require('./routes/webhooks'));

app.use(express.json({ limit: '100kb' }));

// Uploaded photos. Names are random, so listing is off and files are cached
// for good; cross-origin so the web app on another origin can show them.
app.use('/uploads', (req, res, next) => {
  res.setHeader('Cross-Origin-Resource-Policy', 'cross-origin');
  next();
}, express.static(config.uploadDir, { index: false, dotfiles: 'deny', maxAge: '30d', immutable: true }));

app.get('/api/health', (req, res) => res.json({ ok: true, stripeMockMode: config.stripe.mockMode }));
app.use('/api', limits.api);
app.use('/api/catalog', require('./routes/catalog'));
app.use('/api/auth', require('./routes/auth'));
app.use('/api/wallet', require('./routes/wallet'));
app.use('/api/pros', require('./routes/pros'));
app.use('/api/jobs', require('./routes/jobs'));
app.use('/api/admin', require('./routes/admin'));
app.use('/api/uploads', require('./routes/uploads'));

app.use(notFound);
app.use(errorHandler);

module.exports = app;
