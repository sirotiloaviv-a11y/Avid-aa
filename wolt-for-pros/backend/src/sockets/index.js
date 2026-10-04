const { Server } = require('socket.io');
const config = require('../config');
const { prisma } = require('../db');
const { verifyToken } = require('../middleware/auth');
const { ACTIVE_JOB_STATUSES } = require('../domain/constants');
const { haversineKm, etaMinutes, isValidCoordinate } = require('../domain/geo');
const realtime = require('../realtime');
const locationStore = require('../services/locationStore');

const LOCATION_MIN_INTERVAL_MS = 1000;
const LOCATION_PERSIST_INTERVAL_MS = 15000;

function safeAck(ack, payload) {
  if (typeof ack === 'function') ack(payload);
}

function locationPayload(jobId, job, loc) {
  const distanceKm = haversineKm({ lat: loc.lat, lng: loc.lng }, { lat: job.latitude, lng: job.longitude });
  return {
    jobId,
    lat: loc.lat,
    lng: loc.lng,
    heading: loc.heading ?? null,
    at: loc.at,
    distanceKm: Math.round(distanceKm * 100) / 100,
    etaMinutes: etaMinutes(distanceKm),
  };
}

function initSockets(httpServer) {
  const io = new Server(httpServer, { cors: { origin: config.frontendUrl } });
  realtime.setIo(io);

  io.use(async (socket, next) => {
    try {
      const payload = verifyToken(socket.handshake.auth && socket.handshake.auth.token);
      const user = await prisma.user.findUnique({ where: { id: payload.sub }, include: { profile: true } });
      if (!user) return next(new Error('unauthorized'));
      socket.data.user = user;
      return next();
    } catch {
      return next(new Error('unauthorized'));
    }
  });

  io.on('connection', (socket) => {
    const user = socket.data.user;
    socket.join(realtime.rooms.user(user.id));
    if (user.role === 'admin') socket.join(realtime.rooms.admins());
    if (user.role === 'tradesperson' && user.profile) socket.join(realtime.rooms.pros(user.profile.serviceType));

    let lastLocationAt = 0;
    let lastPersistAt = 0;

    // Clients and tradespeople join a job's room to receive its live updates.
    socket.on('job:subscribe', async (msg, ack) => {
      try {
        const jobId = msg && msg.jobId;
        const job = jobId ? await prisma.job.findUnique({ where: { id: jobId }, include: { tradesperson: true } }) : null;
        const allowed = job && (user.role === 'admin' || job.clientId === user.id || job.tradespersonId === user.id);
        if (!allowed) return safeAck(ack, { ok: false, error: 'not_allowed' });

        socket.join(realtime.rooms.job(jobId));
        let location = null;
        if (job.tradespersonId) {
          const live = locationStore.get(job.tradespersonId);
          const stored = job.tradesperson && job.tradesperson.latitude != null
            ? { lat: job.tradesperson.latitude, lng: job.tradesperson.longitude, at: null }
            : null;
          const loc = live || stored;
          if (loc) location = locationPayload(jobId, job, loc);
        }
        return safeAck(ack, { ok: true, location });
      } catch (err) {
        console.error('[socket] job:subscribe', err);
        return safeAck(ack, { ok: false, error: 'server_error' });
      }
    });

    socket.on('job:unsubscribe', (msg) => {
      if (msg && msg.jobId) socket.leave(realtime.rooms.job(msg.jobId));
    });

    // Tradesperson GPS stream. Relayed to the client of each active job.
    socket.on('location:update', async (msg, ack) => {
      try {
        if (user.role !== 'tradesperson') return safeAck(ack, { ok: false, error: 'not_allowed' });
        const lat = Number(msg && msg.lat);
        const lng = Number(msg && msg.lng);
        if (!isValidCoordinate(lat, lng)) return safeAck(ack, { ok: false, error: 'bad_coordinates' });

        const now = Date.now();
        if (now - lastLocationAt < LOCATION_MIN_INTERVAL_MS) return safeAck(ack, { ok: true, throttled: true });
        lastLocationAt = now;

        const heading = Number.isFinite(Number(msg.heading)) ? Number(msg.heading) : null;
        const loc = { lat, lng, heading, at: new Date(now).toISOString() };
        locationStore.set(user.id, loc);

        const jobs = await prisma.job.findMany({
          where: { tradespersonId: user.id, status: { in: ACTIVE_JOB_STATUSES } },
          select: { id: true, latitude: true, longitude: true },
        });
        for (const job of jobs) {
          realtime.toJob(job.id, 'pro:location', locationPayload(job.id, job, loc));
        }

        if (now - lastPersistAt >= LOCATION_PERSIST_INTERVAL_MS) {
          lastPersistAt = now;
          await prisma.user.update({ where: { id: user.id }, data: { latitude: lat, longitude: lng } });
        }
        return safeAck(ack, { ok: true, deliveredTo: jobs.length });
      } catch (err) {
        console.error('[socket] location:update', err);
        return safeAck(ack, { ok: false, error: 'server_error' });
      }
    });
  });

  return io;
}

module.exports = { initSockets };
