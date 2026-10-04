import fs from 'node:fs';
import path from 'node:path';
import express from 'express';
import { HttpError } from './lib/errors.js';

const asyncRoute = (handler) => (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);

function securityHeaders(_req, res, next) {
  res.set({
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Cross-Origin-Opener-Policy': 'same-origin',
  });
  next();
}

export function createApp(brain, { staticDir, logger = console } = {}) {
  const app = express();
  app.disable('x-powered-by');
  app.use(securityHeaders);
  app.use(express.json({ limit: '16kb' }));

  const api = express.Router();
  api.use((_req, res, next) => {
    res.set('Cache-Control', 'no-store');
    next();
  });

  api.get('/health', (_req, res) => {
    res.json({ status: 'ok', service: 'veyra-security-brain', time: new Date().toISOString() });
  });

  // Everything the dashboard needs in one round-trip.
  api.get('/dashboard', (_req, res) => res.json(brain.dashboard()));

  api.get('/risk-score', (_req, res) => res.json(brain.riskScore()));

  api.get('/recommendations', (req, res) => {
    const limit = req.query.limit === undefined ? undefined : Number.parseInt(req.query.limit, 10);
    if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 200)) {
      throw new HttpError(400, 'limit must be an integer between 1 and 200');
    }
    res.json({ recommendations: brain.recommendations({ limit }) });
  });

  api.get('/integrations', (_req, res) => res.json({ integrations: brain.listIntegrations() }));
  api.get('/integrations/:id', (req, res) => res.json(brain.getIntegration(req.params.id)));

  api.post('/integrations/:id/connect', asyncRoute(async (req, res) => {
    res.json(await brain.connect(req.params.id, req.body?.credentials ?? {}));
  }));

  api.post('/integrations/:id/disconnect', (req, res) => res.json(brain.disconnect(req.params.id)));

  api.patch('/integrations/:id', (req, res) => res.json(brain.setEnabled(req.params.id, req.body?.enabled)));

  api.post('/integrations/:id/sync', asyncRoute(async (req, res) => res.json(await brain.sync(req.params.id))));

  api.post('/sync', asyncRoute(async (_req, res) => res.json({ integrations: await brain.syncAll() })));

  api.get('/findings', (req, res) => {
    const pick = (key) => (typeof req.query[key] === 'string' && req.query[key] ? req.query[key] : undefined);
    const findings = brain.listFindings({ provider: pick('provider'), severity: pick('severity'), status: pick('status'), q: pick('q') });
    res.json({ total: findings.length, findings });
  });

  api.get('/findings/:id', (req, res) => res.json(brain.getFinding(req.params.id)));

  api.post('/findings/:id/remediate', (req, res) => res.status(202).json(brain.remediate(req.params.id)));

  api.post('/demo/reset', asyncRoute(async (_req, res) => {
    await brain.reset();
    res.json(brain.dashboard());
  }));

  api.use((req, _res, next) => next(new HttpError(404, `No route for ${req.method} ${req.baseUrl}${req.path}`)));

  app.use('/api', api);

  // In production the built React app is served from the same origin.
  if (staticDir && fs.existsSync(path.join(staticDir, 'index.html'))) {
    app.use(express.static(staticDir, { index: false, maxAge: '1h' }));
    app.get('*', (_req, res) => res.sendFile(path.join(staticDir, 'index.html')));
  }

  // eslint-disable-next-line no-unused-vars
  app.use((error, _req, res, _next) => {
    if (error.type === 'entity.parse.failed') error = new HttpError(400, 'Request body is not valid JSON');
    if (error.type === 'entity.too.large') error = new HttpError(413, 'Request body is too large');
    const status = Number.isInteger(error.status) ? error.status : 500;
    if (status >= 500) logger.error(error);
    res.status(status).json({
      error: status >= 500 && !(error instanceof HttpError) ? 'Internal server error' : error.message,
      ...(error.details ?? {}),
    });
  });

  return app;
}
