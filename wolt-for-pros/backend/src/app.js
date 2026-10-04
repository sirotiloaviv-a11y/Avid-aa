const express = require('express');
const cors = require('cors');
const config = require('./config');
const { notFound, errorHandler } = require('./middleware/errors');

const app = express();
app.disable('x-powered-by');
app.use(cors({ origin: config.frontendUrl }));

// Stripe webhooks need the raw body, so they go before the JSON parser.
app.use('/api/webhooks', require('./routes/webhooks'));

app.use(express.json({ limit: '100kb' }));

app.get('/api/health', (req, res) => res.json({ ok: true, stripeMockMode: config.stripe.mockMode }));
app.use('/api/catalog', require('./routes/catalog'));
app.use('/api/auth', require('./routes/auth'));
app.use('/api/wallet', require('./routes/wallet'));
app.use('/api/pros', require('./routes/pros'));
app.use('/api/jobs', require('./routes/jobs'));
app.use('/api/admin', require('./routes/admin'));

app.use(notFound);
app.use(errorHandler);

module.exports = app;
