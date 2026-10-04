'use client';

// In-browser stand-in for the Express API and Socket.io server, used when no
// backend is reachable (see ./mode.js). It mirrors the backend's routes,
// payload shapes and business rules (backend/src/services) closely enough that
// every page runs unchanged. State lives in localStorage so it survives
// reloads; resetDemo() restores the seed.

import { ApiError } from '../errors.js';

const STORAGE_KEY = 'wfp_demo_state_v1';
const FEE_RATE = 0.15;
const MAX_CODE_ATTEMPTS = 5;
const FLAG_WINDOW_MS = 30 * 24 * 60 * 60 * 1000;
const RESPONSE_DELAY_MS = 180;
const DRIVE_STEP_MS = 1000;
const DRIVE_STEPS = 30;
const AVERAGE_SPEED_KMH = 30;

const CATALOG = [
  { type: 'electrician', label: 'Electrician', min: 250, max: 650 },
  { type: 'plumber', label: 'Plumber', min: 300, max: 750 },
  { type: 'handyman', label: 'Handyman', min: 180, max: 450 },
].map((s) => ({ ...s, estimate: Math.round((s.min + s.max) / 2) }));

export const DEMO_PHONE_BY_ROLE = {
  client: '0501111111',
  tradesperson: '0502222222',
  admin: '0500000000',
};

export const DEMO_ACTIVE_JOB_ID = 'job_outlet';

// ---------------------------------------------------------------------------
// Seed

const minutesAgo = (m) => new Date(Date.now() - m * 60 * 1000).toISOString();

function seed() {
  const users = [
    { id: 'u_noa', name: 'Noa (Admin)', phone: '0500000000', role: 'admin', latitude: null, longitude: null },
    { id: 'u_dana', name: 'Dana Levi', phone: '0501111111', role: 'client', latitude: 32.0853, longitude: 34.7818 },
    { id: 'u_omer', name: 'Omer Ben-David', phone: '0505555555', role: 'client', latitude: 32.0741, longitude: 34.7922 },
    { id: 'u_yossi', name: 'Yossi Cohen', phone: '0502222222', role: 'tradesperson', latitude: 32.0655, longitude: 34.7695 },
    { id: 'u_moshe', name: 'Moshe Plumbing', phone: '0503333333', role: 'tradesperson', latitude: 32.0950, longitude: 34.7850 },
    { id: 'u_avi', name: 'Avi Mizrahi', phone: '0504444444', role: 'tradesperson', latitude: 32.0600, longitude: 34.7750 },
  ];
  const profiles = {
    u_yossi: { licenseNumber: 'EL-48213', serviceType: 'electrician', status: 'active', fraudScore: 0 },
    u_moshe: { licenseNumber: 'PL-11902', serviceType: 'plumber', status: 'active', fraudScore: 0 },
    u_avi: { licenseNumber: 'HM-73001', serviceType: 'handyman', status: 'active', fraudScore: 1 },
  };
  const wallets = {
    u_yossi: { id: 'w_yossi', balance: 35000, locked: 5000 },
    u_moshe: { id: 'w_moshe', balance: 3000, locked: 0 },
    u_avi: { id: 'w_avi', balance: 20000, locked: 6000 },
  };

  const job = (over) => ({
    tradespersonId: null,
    address: null,
    finalCents: null,
    feeCents: null,
    codeAttempts: 0,
    status: 'requested',
    flaggedAt: null,
    flagReason: null,
    resolution: null,
    resolutionNote: null,
    resolvedAt: null,
    assignedAt: null,
    startedAt: null,
    completedAt: null,
    cancelledAt: null,
    ...over,
  });

  const jobs = [
    job({
      id: DEMO_ACTIVE_JOB_ID,
      clientId: 'u_dana',
      tradespersonId: 'u_yossi',
      serviceType: 'electrician',
      description: 'Power Outlet Replacement: burnt socket next to the kitchen counter',
      address: 'Dizengoff St 120, Tel Aviv',
      latitude: 32.0853,
      longitude: 34.7818,
      estimatedCents: 40000,
      feeCents: 6000,
      completionCode: '4829',
      status: 'assigned',
      assignedAt: minutesAgo(6),
      createdAt: minutesAgo(9),
    }),
    job({
      id: 'job_flagged',
      clientId: 'u_omer',
      tradespersonId: 'u_avi',
      serviceType: 'handyman',
      description: 'Mount a TV on a concrete wall and hide the cables',
      address: 'Frishman St 40, Tel Aviv',
      latitude: 32.0805,
      longitude: 34.7735,
      estimatedCents: 40000,
      finalCents: 15000,
      feeCents: 6000,
      completionCode: '1937',
      status: 'flagged',
      flaggedAt: minutesAgo(60 * 26),
      flagReason: 'Unusual low price ₪150 vs ₪400 estimate',
      assignedAt: minutesAgo(60 * 28),
      startedAt: minutesAgo(60 * 27),
      completedAt: minutesAgo(60 * 26),
      createdAt: minutesAgo(60 * 29),
    }),
    job({
      id: 'job_open_1',
      clientId: 'u_omer',
      serviceType: 'electrician',
      description: 'Install two ceiling lights in the living room',
      address: 'Ibn Gabirol St 30, Tel Aviv',
      latitude: 32.0790,
      longitude: 34.7810,
      estimatedCents: 45000,
      completionCode: '5521',
      createdAt: minutesAgo(4),
    }),
    job({
      id: 'job_open_2',
      clientId: 'u_omer',
      serviceType: 'electrician',
      description: 'Breaker trips whenever the AC and oven run together',
      address: 'Allenby St 50, Tel Aviv',
      latitude: 32.0680,
      longitude: 34.7710,
      estimatedCents: 45000,
      completionCode: '0864',
      createdAt: minutesAgo(12),
    }),
    job({
      id: 'job_open_3',
      clientId: 'u_dana',
      serviceType: 'plumber',
      description: 'Kitchen sink is blocked and draining very slowly',
      address: 'Ben Yehuda St 80, Tel Aviv',
      latitude: 32.0830,
      longitude: 34.7700,
      estimatedCents: 52500,
      completionCode: '3310',
      createdAt: minutesAgo(18),
    }),
  ];

  const transactions = [
    { id: 't1', userId: 'u_yossi', amountCents: 40000, type: 'deposit', jobId: null, note: 'Card top-up', createdAt: minutesAgo(60 * 24 * 2) },
    { id: 't2', userId: 'u_yossi', amountCents: -5000, type: 'fee_hold', jobId: DEMO_ACTIVE_JOB_ID, note: 'Platform fee held on job acceptance', createdAt: minutesAgo(6) },
    { id: 't3', userId: 'u_moshe', amountCents: 3000, type: 'deposit', jobId: null, note: 'Card top-up', createdAt: minutesAgo(60 * 24 * 5) },
    { id: 't4', userId: 'u_avi', amountCents: 26000, type: 'deposit', jobId: null, note: 'Card top-up', createdAt: minutesAgo(60 * 24 * 7) },
    { id: 't5', userId: 'u_avi', amountCents: -6000, type: 'fee_hold', jobId: 'job_flagged', note: 'Platform fee held on job acceptance', createdAt: minutesAgo(60 * 28) },
  ];

  return { seq: 100, users, profiles, wallets, jobs, transactions };
}

// ---------------------------------------------------------------------------
// Persistence

let state = null;

function db() {
  if (state) return state;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) state = JSON.parse(raw);
  } catch {
    state = null;
  }
  if (!state || !Array.isArray(state.jobs)) state = seed();
  return state;
}

function save() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage full or blocked: the demo keeps working in memory.
  }
}

function nextId(prefix) {
  const s = db();
  s.seq += 1;
  return `${prefix}_${Date.now().toString(36)}${s.seq}`;
}

export function resetDemo() {
  stopAllDrives();
  state = seed();
  save();
}

// ---------------------------------------------------------------------------
// Fake socket: a single in-tab event bus

const listeners = new Map();

export const demoSocket = {
  connected: true,
  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
  },
  off(event, fn) {
    if (listeners.has(event)) listeners.get(event).delete(fn);
  },
  emit(event, payload, ack) {
    setTimeout(() => {
      const result = handleSocketEmit(event, payload || {});
      if (typeof ack === 'function') ack(result);
    }, 0);
  },
  disconnect() {},
};

function dispatch(event, payload) {
  setTimeout(() => {
    const set = listeners.get(event);
    if (set) [...set].forEach((fn) => fn(payload));
  }, 0);
}

// ---------------------------------------------------------------------------
// Helpers

const toMoney = (cents) => (cents == null ? null : cents / 100);
const feeFor = (cents) => Math.round(cents * FEE_RATE);

function haversineKm(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

const fail = (status, message, code, details) => {
  throw new ApiError(message, status, code, details);
};

const findUser = (id) => db().users.find((u) => u.id === id) || null;
const findJob = (id) => db().jobs.find((j) => j.id === id) || fail(404, 'Job not found', 'JOB_NOT_FOUND');
const profileOf = (userId) => db().profiles[userId] || null;
const isActive = (job) => job.status === 'assigned' || job.status === 'in_progress';

function walletOf(userId) {
  const s = db();
  if (!s.wallets[userId]) s.wallets[userId] = { id: `w_${userId}`, balance: 0, locked: 0 };
  return s.wallets[userId];
}

function ledger(userId, amountCents, type, jobId, note) {
  db().transactions.unshift({ id: nextId('t'), userId, amountCents, type, jobId: jobId || null, note: note || null, createdAt: new Date().toISOString() });
}

function publicUser(u) {
  return u && { id: u.id, name: u.name, phone: u.phone, role: u.role, latitude: u.latitude, longitude: u.longitude };
}

function serializeProfile(userId) {
  const p = profileOf(userId);
  return p && { userId, ...p };
}

function serializeWallet(userId) {
  const w = db().wallets[userId];
  return w && { id: w.id, tradespersonId: userId, balance: toMoney(w.balance), lockedBalance: toMoney(w.locked) };
}

function serializeJob(job, viewer) {
  if (!job) return null;
  const isClient = viewer && viewer.id === job.clientId;
  const isAdmin = viewer && viewer.role === 'admin';
  const isPro = viewer && job.tradespersonId && viewer.id === job.tradespersonId;
  const out = {
    id: job.id,
    clientId: job.clientId,
    tradespersonId: job.tradespersonId,
    serviceType: job.serviceType,
    description: job.description,
    address: job.address,
    latitude: job.latitude,
    longitude: job.longitude,
    estimatedPrice: toMoney(job.estimatedCents),
    finalPrice: toMoney(job.finalCents),
    platformFee: toMoney(job.feeCents),
    status: job.status,
    flaggedAt: job.flaggedAt,
    flagReason: job.flagReason,
    resolution: job.resolution,
    resolutionNote: job.resolutionNote,
    resolvedAt: job.resolvedAt,
    assignedAt: job.assignedAt,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    cancelledAt: job.cancelledAt,
    createdAt: job.createdAt,
  };
  if (isClient || isAdmin) out.completionCode = job.completionCode;
  if (isAdmin) out.codeAttempts = job.codeAttempts;

  const client = findUser(job.clientId);
  if (client) {
    out.client = { id: client.id, name: client.name };
    if (isPro || isAdmin) out.client.phone = client.phone;
  }
  const pro = job.tradespersonId && findUser(job.tradespersonId);
  if (pro) {
    const p = profileOf(pro.id);
    out.tradesperson = {
      id: pro.id,
      name: pro.name,
      phone: isClient || isAdmin || isPro ? pro.phone : undefined,
      latitude: pro.latitude,
      longitude: pro.longitude,
      licenseNumber: p && p.licenseNumber,
      serviceType: p && p.serviceType,
    };
    if (isAdmin) {
      out.tradesperson.status = p && p.status;
      out.tradesperson.fraudScore = p && p.fraudScore;
      out.tradesperson.wallet = serializeWallet(pro.id);
    }
  }
  return out;
}

function radarExtras(job) {
  const fee = feeFor(job.estimatedCents);
  return { feeAmount: toMoney(fee), payoutEstimate: toMoney(job.estimatedCents - fee) };
}

function broadcastJob(job) {
  dispatch('job:updated', serializeJob(job, null));
}

function notifyWallet(userId) {
  dispatch('wallet:updated', serializeWallet(userId));
}

function flagsInWindow(userId) {
  const since = Date.now() - FLAG_WINDOW_MS;
  return db().jobs.filter((j) => j.tradespersonId === userId && j.flaggedAt && new Date(j.flaggedAt).getTime() >= since && j.resolution !== 'approved').length;
}

// The seed's held amounts can differ from a job's recorded fee (e.g. Yossi has
// ₪50 locked against a ₪60 fee), so releases take what is actually locked and
// the books still balance: total funds change only by the fee charged.
function releaseHold(userId, heldCents, jobId, note) {
  const w = walletOf(userId);
  const fromLocked = Math.min(heldCents || 0, w.locked);
  if (fromLocked <= 0) return;
  w.locked -= fromLocked;
  w.balance += fromLocked;
  ledger(userId, fromLocked, 'refund', jobId, note || 'Held fee released');
}

function settleFee(userId, heldCents, finalFeeCents, jobId, note) {
  const w = walletOf(userId);
  const fromLocked = Math.min(heldCents || 0, w.locked);
  w.locked -= fromLocked;
  w.balance += fromLocked - finalFeeCents;
  ledger(userId, -finalFeeCents, 'fee_deduction', jobId, note || 'Platform fee charged');
  if (fromLocked > finalFeeCents) ledger(userId, fromLocked - finalFeeCents, 'refund', jobId, 'Unused part of the held fee released');
}

// ---------------------------------------------------------------------------
// Driver simulation (runs in the "server" so it keeps going across views)

const drives = new Map(); // jobId -> interval id

export function isDemoDriving(jobId) {
  return drives.has(jobId);
}

function stopDrive(jobId, arrived = false) {
  if (!drives.has(jobId)) return;
  clearInterval(drives.get(jobId));
  drives.delete(jobId);
  dispatch('demo:drive', { jobId, active: false, arrived });
}

function stopAllDrives() {
  [...drives.keys()].forEach((id) => stopDrive(id));
}

export function toggleDemoDrive(jobId) {
  if (drives.has(jobId)) {
    stopDrive(jobId);
    return false;
  }
  const job = db().jobs.find((j) => j.id === jobId);
  const pro = job && job.tradespersonId && findUser(job.tradespersonId);
  if (!job || !pro || job.status !== 'assigned') return false;

  const start = { lat: pro.latitude ?? job.latitude + 0.02, lng: pro.longitude ?? job.longitude - 0.012 };
  const end = { lat: job.latitude, lng: job.longitude };
  let step = 0;
  const timer = setInterval(() => {
    step += 1;
    const t = Math.min(1, step / DRIVE_STEPS);
    // Slight curve so the path doesn't look like a ruler line.
    const bend = Math.sin(t * Math.PI) * 0.0025;
    moveTradesperson(pro.id, {
      lat: start.lat + (end.lat - start.lat) * t + bend,
      lng: start.lng + (end.lng - start.lng) * t - bend,
    });
    if (t >= 1) stopDrive(jobId, true);
  }, DRIVE_STEP_MS);
  drives.set(jobId, timer);
  dispatch('demo:drive', { jobId, active: true });
  return true;
}

function moveTradesperson(userId, { lat, lng }) {
  const pro = findUser(userId);
  if (!pro) return;
  pro.latitude = lat;
  pro.longitude = lng;
  save();
  const at = new Date().toISOString();
  db().jobs.filter((j) => j.tradespersonId === userId && isActive(j)).forEach((job) => {
    const distanceKm = haversineKm({ lat, lng }, { lat: job.latitude, lng: job.longitude });
    dispatch('pro:location', {
      jobId: job.id,
      lat,
      lng,
      at,
      distanceKm: Math.round(distanceKm * 100) / 100,
      etaMinutes: Math.max(0, Math.ceil((distanceKm / AVERAGE_SPEED_KMH) * 60)),
    });
  });
}

// ---------------------------------------------------------------------------
// Socket messages from the page

let currentUserId = null;

function handleSocketEmit(event, payload) {
  if (event === 'job:subscribe') {
    const job = db().jobs.find((j) => j.id === payload.jobId);
    if (!job) return { ok: false, error: 'not_found' };
    const pro = job.tradespersonId && findUser(job.tradespersonId);
    let location = null;
    if (pro && pro.latitude != null) {
      const distanceKm = haversineKm({ lat: pro.latitude, lng: pro.longitude }, { lat: job.latitude, lng: job.longitude });
      location = { jobId: job.id, lat: pro.latitude, lng: pro.longitude, distanceKm, etaMinutes: Math.ceil((distanceKm / AVERAGE_SPEED_KMH) * 60), at: null };
    }
    return { ok: true, location };
  }
  if (event === 'location:update') {
    const user = currentUserId && findUser(currentUserId);
    if (!user || user.role !== 'tradesperson') return { ok: false, error: 'not_allowed' };
    if (!Number.isFinite(payload.lat) || !Number.isFinite(payload.lng)) return { ok: false, error: 'bad_coordinates' };
    moveTradesperson(user.id, payload);
    return { ok: true };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// HTTP routes

function authUser(token) {
  const id = token && token.startsWith('demo:') ? token.slice(5) : null;
  const user = id && findUser(id);
  if (!user) fail(401, 'Invalid or expired token', 'UNAUTHENTICATED');
  currentUserId = user.id;
  return user;
}

function requireRole(user, ...roles) {
  if (!roles.includes(user.role)) fail(403, `This action requires role: ${roles.join(' or ')}`, 'FORBIDDEN');
}

function authResponse(user) {
  currentUserId = user.id;
  return { token: `demo:${user.id}`, user: publicUser(user), profile: serializeProfile(user.id) };
}

/** @type {Array<[string, RegExp, (ctx: any) => any, { auth?: boolean }?]>} */
const routes = [
  ['GET', /^\/api\/health$/, () => ({ ok: true, demo: true })],
  ['GET', /^\/api\/catalog$/, () => ({
    currency: 'ILS',
    feeRate: FEE_RATE,
    services: CATALOG,
    topUp: { presets: [100, 200, 500], min: 20, max: 5000, mockMode: true },
    auth: { otpRequired: false },
  })],
  ['POST', /^\/api\/auth\/otp\/request$/, () => ({ sent: true, devCode: '000000' })],

  ['POST', /^\/api\/auth\/login$/, ({ body }) => {
    const user = db().users.find((u) => u.phone === String(body.phone || '').trim());
    if (!user) fail(404, 'No account with this phone number. Register first.', 'NO_ACCOUNT');
    return authResponse(user);
  }],
  ['POST', /^\/api\/auth\/register$/, ({ body }) => {
    const s = db();
    const phone = String(body.phone || '').trim();
    if (!/^\+?[0-9]{9,15}$/.test(phone)) fail(400, 'phone: Phone must be 9-15 digits', 'VALIDATION_ERROR');
    if (!body.name || body.name.trim().length < 2) fail(400, 'name: Enter your name', 'VALIDATION_ERROR');
    if (s.users.some((u) => u.phone === phone)) fail(409, 'This phone number is already registered', 'PHONE_TAKEN');
    const role = body.role === 'tradesperson' ? 'tradesperson' : 'client';
    const user = { id: nextId('u'), name: body.name.trim(), phone, role, latitude: 32.0853, longitude: 34.7818 };
    s.users.push(user);
    if (role === 'tradesperson') {
      s.profiles[user.id] = { licenseNumber: body.licenseNumber || 'DEMO', serviceType: body.serviceType || 'electrician', status: 'inactive', fraudScore: 0 };
      walletOf(user.id);
    }
    return authResponse(user);
  }],
  ['GET', /^\/api\/auth\/me$/, ({ user }) => ({ user: publicUser(user), profile: serializeProfile(user.id) }), { auth: true }],

  ['GET', /^\/api\/wallet\/balance$/, ({ user }) => {
    requireRole(user, 'tradesperson');
    walletOf(user.id);
    return {
      wallet: serializeWallet(user.id),
      currency: 'ILS',
      feeRate: FEE_RATE,
      transactions: db().transactions.filter((t) => t.userId === user.id).slice(0, 25).map((t) => ({
        id: t.id, amount: toMoney(t.amountCents), type: t.type, jobId: t.jobId, note: t.note, createdAt: t.createdAt,
      })),
    };
  }, { auth: true }],
  ['POST', /^\/api\/wallet\/deposit$/, ({ user, body }) => {
    requireRole(user, 'tradesperson');
    const amount = Number(body.amount);
    if (!Number.isInteger(amount) || amount < 20 || amount > 5000) fail(400, 'amount: Between ₪20 and ₪5,000', 'VALIDATION_ERROR');
    walletOf(user.id).balance += amount * 100;
    ledger(user.id, amount * 100, 'deposit', null, 'Card top-up (demo)');
    notifyWallet(user.id);
    return { wallet: serializeWallet(user.id) };
  }, { auth: true }],
  ['POST', /^\/api\/wallet\/checkout-session$/, ({ user }) => {
    requireRole(user, 'tradesperson');
    return { mock: true, url: null };
  }, { auth: true }],
  ['GET', /^\/api\/wallet\/checkout-session\/[^/]+$/, ({ user }) => ({ status: 'paid', credited: false, wallet: serializeWallet(user.id) }), { auth: true }],

  ['GET', /^\/api\/pros\/me$/, ({ user }) => {
    requireRole(user, 'tradesperson');
    walletOf(user.id);
    const active = db().jobs.find((j) => j.tradespersonId === user.id && isActive(j));
    return { user: publicUser(user), profile: serializeProfile(user.id), wallet: serializeWallet(user.id), activeJob: serializeJob(active, user) };
  }, { auth: true }],
  ['POST', /^\/api\/pros\/me\/availability$/, ({ user, body }) => {
    requireRole(user, 'tradesperson');
    const p = profileOf(user.id);
    if (p.status === 'suspended') fail(403, 'Your account is suspended pending review', 'ACCOUNT_SUSPENDED');
    p.status = body.online ? 'active' : 'inactive';
    return { profile: serializeProfile(user.id) };
  }, { auth: true }],

  ['POST', /^\/api\/jobs\/create$/, ({ user, body }) => {
    requireRole(user, 'client');
    const svc = CATALOG.find((c) => c.type === body.serviceType) || fail(400, 'serviceType: Pick a service', 'VALIDATION_ERROR');
    if (!body.description || body.description.trim().length < 5) fail(400, 'description: Describe the problem in a few words', 'VALIDATION_ERROR');
    const job = {
      id: nextId('job'),
      clientId: user.id,
      tradespersonId: null,
      serviceType: svc.type,
      description: body.description.trim(),
      address: body.address || null,
      latitude: Number(body.latitude),
      longitude: Number(body.longitude),
      estimatedCents: svc.estimate * 100,
      finalCents: null,
      feeCents: null,
      completionCode: String(Math.floor(Math.random() * 10000)).padStart(4, '0'),
      codeAttempts: 0,
      status: 'requested',
      flaggedAt: null, flagReason: null, resolution: null, resolutionNote: null, resolvedAt: null,
      assignedAt: null, startedAt: null, completedAt: null, cancelledAt: null,
      createdAt: new Date().toISOString(),
    };
    db().jobs.unshift(job);
    user.latitude = job.latitude;
    user.longitude = job.longitude;
    dispatch('job:new', { ...serializeJob(job, null), ...radarExtras(job) });
    return { job: serializeJob(job, user) };
  }, { auth: true }],
  ['GET', /^\/api\/jobs\/mine$/, ({ user }) => {
    const key = user.role === 'tradesperson' ? 'tradespersonId' : 'clientId';
    const jobs = db().jobs.filter((j) => j[key] === user.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    return { jobs: jobs.map((j) => serializeJob(j, user)) };
  }, { auth: true }],
  ['GET', /^\/api\/jobs\/nearby$/, ({ user, query }) => {
    requireRole(user, 'tradesperson');
    const p = profileOf(user.id);
    const origin = query.lat != null ? { lat: Number(query.lat), lng: Number(query.lng) } : { lat: user.latitude, lng: user.longitude };
    const radius = Number(query.radiusKm) || 25;
    const available = walletOf(user.id).balance;
    const jobs = db().jobs
      .filter((j) => j.status === 'requested' && j.serviceType === p.serviceType)
      .map((j) => {
        const d = haversineKm(origin, { lat: j.latitude, lng: j.longitude });
        return {
          ...serializeJob(j, user),
          ...radarExtras(j),
          distanceKm: Math.round(d * 10) / 10,
          etaMinutes: Math.ceil((d / AVERAGE_SPEED_KMH) * 60),
          canAfford: available >= feeFor(j.estimatedCents),
        };
      })
      .filter((j) => j.distanceKm <= radius)
      .sort((a, b) => a.distanceKm - b.distanceKm);
    return { jobs };
  }, { auth: true }],
  ['GET', /^\/api\/jobs\/([^/]+)$/, ({ user, params }) => {
    const job = findJob(params[0]);
    if (user.role !== 'admin' && job.clientId !== user.id && job.tradespersonId !== user.id) fail(403, 'You are not part of this job', 'FORBIDDEN');
    return { job: serializeJob(job, user) };
  }, { auth: true }],
  ['POST', /^\/api\/jobs\/([^/]+)\/accept$/, ({ user, params, body }) => {
    requireRole(user, 'tradesperson');
    const p = profileOf(user.id);
    if (p.status === 'suspended') fail(403, 'Your account is suspended pending review. Contact support.', 'ACCOUNT_SUSPENDED');
    if (p.status !== 'active') fail(409, 'Go online before accepting jobs', 'NOT_ONLINE');
    const job = findJob(params[0]);
    if (job.serviceType !== p.serviceType) fail(403, `This job needs a ${job.serviceType}`, 'WRONG_SERVICE_TYPE');
    if (job.status !== 'requested') fail(409, 'This job is no longer available', 'JOB_NOT_AVAILABLE');
    if (db().jobs.some((j) => j.tradespersonId === user.id && isActive(j))) fail(409, 'Finish your current job before accepting another', 'ALREADY_ON_JOB');
    const fee = feeFor(job.estimatedCents);
    const w = walletOf(user.id);
    if (w.balance < fee) {
      fail(402, 'Your available balance does not cover the platform fee for this job. Top up your wallet to accept it.', 'INSUFFICIENT_BALANCE', { requiredFee: toMoney(fee) });
    }
    w.balance -= fee;
    w.locked += fee;
    ledger(user.id, -fee, 'fee_hold', job.id, 'Platform fee held on job acceptance');
    Object.assign(job, { status: 'assigned', tradespersonId: user.id, feeCents: fee, assignedAt: new Date().toISOString() });
    if (Number.isFinite(body.latitude)) {
      user.latitude = body.latitude;
      user.longitude = body.longitude;
    }
    dispatch('job:taken', { id: job.id });
    broadcastJob(job);
    notifyWallet(user.id);
    return { job: serializeJob(job, user) };
  }, { auth: true }],
  ['POST', /^\/api\/jobs\/([^/]+)\/start$/, ({ user, params }) => {
    const job = findJob(params[0]);
    if (job.tradespersonId !== user.id) fail(403, 'This is not your job', 'FORBIDDEN');
    if (job.status !== 'assigned') fail(409, `Cannot start a job that is ${job.status}`, 'INVALID_STATUS');
    stopDrive(job.id);
    Object.assign(job, { status: 'in_progress', startedAt: new Date().toISOString() });
    broadcastJob(job);
    return { job: serializeJob(job, user) };
  }, { auth: true }],
  ['POST', /^\/api\/jobs\/([^/]+)\/verify-and-complete$/, ({ user, params, body }) => {
    const job = findJob(params[0]);
    if (job.tradespersonId !== user.id) fail(403, 'This is not your job', 'FORBIDDEN');
    if (!isActive(job)) fail(409, `Cannot complete a job that is ${job.status}`, 'INVALID_STATUS');
    if (job.codeAttempts >= MAX_CODE_ATTEMPTS) fail(423, 'Too many wrong codes. This job is locked; contact support.', 'CODE_LOCKED');
    const code = String(body.completionCode || '').trim();
    if (!/^\d{4}$/.test(code)) fail(400, 'completionCode: The code is 4 digits', 'VALIDATION_ERROR');
    const finalPrice = Number(body.finalPrice);
    if (!(finalPrice > 0)) fail(400, 'finalPrice: Enter the final price', 'VALIDATION_ERROR');
    if (code !== job.completionCode) {
      job.codeAttempts += 1;
      save();
      const remaining = MAX_CODE_ATTEMPTS - job.codeAttempts;
      fail(400, `Incorrect completion code. ${remaining} attempt(s) left.`, 'WRONG_CODE', { remaining });
    }

    stopDrive(job.id);
    const now = new Date().toISOString();
    const finalCents = Math.round(finalPrice * 100);
    let outcome = 'completed';
    let suspended = false;
    if (finalCents < job.estimatedCents * 0.5) {
      outcome = 'flagged';
      Object.assign(job, {
        status: 'flagged',
        finalCents,
        flaggedAt: now,
        completedAt: now,
        flagReason: `Unusual low price ₪${finalPrice} vs ₪${toMoney(job.estimatedCents)} estimate`,
      });
      const p = profileOf(user.id);
      p.fraudScore += 1;
      if (flagsInWindow(user.id) >= 2 && p.status !== 'suspended') {
        p.status = 'suspended';
        suspended = true;
      }
      dispatch('flagged:new', serializeJob(job, { role: 'admin' }));
    } else {
      const finalFee = feeFor(finalCents);
      settleFee(user.id, job.feeCents, finalFee, job.id);
      Object.assign(job, { status: 'completed', finalCents, feeCents: finalFee, completedAt: now });
    }
    broadcastJob(job);
    notifyWallet(user.id);
    return { outcome, suspended, job: serializeJob(job, user) };
  }, { auth: true }],
  ['POST', /^\/api\/jobs\/([^/]+)\/cancel$/, ({ user, params, body }) => {
    const job = findJob(params[0]);
    const isClient = job.clientId === user.id;
    const isPro = job.tradespersonId === user.id;
    const isAdmin = user.role === 'admin';
    if (!isClient && !isPro && !isAdmin) fail(403, 'You are not part of this job', 'FORBIDDEN');
    const allowed = isAdmin ? ['requested', 'assigned', 'in_progress'] : isClient ? ['requested', 'assigned'] : ['assigned'];
    if (!allowed.includes(job.status)) fail(409, `A ${job.status} job cannot be cancelled by you`, 'INVALID_STATUS');
    stopDrive(job.id);
    const proId = job.tradespersonId;
    if (proId && job.feeCents != null) {
      const who = isClient ? 'client' : isPro ? 'tradesperson' : 'admin';
      releaseHold(proId, job.feeCents, job.id, `Job cancelled by ${who}${body.reason ? `: ${body.reason}` : ''}`);
    }
    if (isPro && !isClient) {
      Object.assign(job, { status: 'requested', tradespersonId: null, feeCents: null, assignedAt: null });
      dispatch('job:new', { ...serializeJob(job, null), ...radarExtras(job) });
    } else {
      Object.assign(job, { status: 'cancelled', cancelledAt: new Date().toISOString() });
      dispatch('job:taken', { id: job.id });
    }
    broadcastJob(job);
    if (proId) notifyWallet(proId);
    return { job: serializeJob(job, user) };
  }, { auth: true }],

  ['GET', /^\/api\/admin\/flagged-jobs$/, ({ user, query }) => {
    requireRole(user, 'admin');
    const state = query.state || 'open';
    const jobs = db().jobs
      .filter((j) => (state === 'open' ? j.status === 'flagged' : state === 'resolved' ? j.flaggedAt && j.resolution : j.flaggedAt))
      .sort((a, b) => (b.flaggedAt || '').localeCompare(a.flaggedAt || ''));
    return { jobs: jobs.map((j) => ({ ...serializeJob(j, user), tradespersonFlagsInWindow: j.tradespersonId ? flagsInWindow(j.tradespersonId) : 0 })) };
  }, { auth: true }],
  ['POST', /^\/api\/admin\/flagged-jobs$/, ({ user, body }) => {
    requireRole(user, 'admin');
    const job = findJob(body.jobId);
    if (job.status !== 'flagged') fail(409, `Job is ${job.status}, not flagged`, 'INVALID_STATUS');
    const now = new Date().toISOString();
    const note = body.note ? `${body.note} (by ${user.name})` : `Resolved by ${user.name}`;
    const proId = job.tradespersonId;
    if (body.action === 'void') {
      releaseHold(proId, job.feeCents, job.id, 'Flagged job voided by admin');
      Object.assign(job, { status: 'cancelled', cancelledAt: now, resolution: 'voided' });
    } else if (body.action === 'approve' || body.action === 'charge_estimate') {
      const approve = body.action === 'approve';
      const fee = feeFor(approve ? job.finalCents : job.estimatedCents);
      settleFee(proId, job.feeCents, fee, job.id, approve ? 'Fee on final price (dispute approved)' : 'Fee on estimated price (dispute rejected)');
      Object.assign(job, { status: 'completed', feeCents: fee, resolution: approve ? 'approved' : 'charged_estimate' });
      if (approve) {
        const p = profileOf(proId);
        p.fraudScore = Math.max(0, p.fraudScore - 1);
      }
    } else {
      fail(400, 'action: approve, charge_estimate or void', 'VALIDATION_ERROR');
    }
    Object.assign(job, { resolutionNote: note, resolvedAt: now });
    broadcastJob(job);
    notifyWallet(proId);
    return { job: serializeJob(job, user) };
  }, { auth: true }],
  ['GET', /^\/api\/admin\/tradespeople$/, ({ user }) => {
    requireRole(user, 'admin');
    const pros = db().users.filter((u) => u.role === 'tradesperson').sort((a, b) => a.name.localeCompare(b.name));
    return {
      tradespeople: pros.map((p) => ({
        id: p.id, name: p.name, phone: p.phone,
        profile: serializeProfile(p.id), wallet: serializeWallet(p.id), flagsInWindow: flagsInWindow(p.id),
      })),
    };
  }, { auth: true }],
  ['POST', /^\/api\/admin\/tradespeople\/([^/]+)\/status$/, ({ user, params, body }) => {
    requireRole(user, 'admin');
    const p = profileOf(params[0]) || fail(404, 'Tradesperson not found', 'NOT_FOUND');
    if (!['active', 'inactive', 'suspended'].includes(body.status)) fail(400, 'status: active, inactive or suspended', 'VALIDATION_ERROR');
    p.status = body.status;
    dispatch('profile:updated', { status: p.status });
    return { profile: serializeProfile(params[0]) };
  }, { auth: true }],
  ['POST', /^\/api\/admin\/wallets\/([^/]+)\/adjust$/, ({ user, params, body }) => {
    requireRole(user, 'admin');
    if (!profileOf(params[0])) fail(404, 'Tradesperson not found', 'NOT_FOUND');
    const cents = Math.round(Number(body.amount) * 100);
    if (!cents) fail(400, 'amount: Must not be zero', 'VALIDATION_ERROR');
    walletOf(params[0]).balance += cents;
    ledger(params[0], cents, 'adjustment', null, `${body.note || 'Manual adjustment'} (by ${user.name})`);
    notifyWallet(params[0]);
    return { wallet: serializeWallet(params[0]) };
  }, { auth: true }],
];

export async function mockRequest({ method, path, body, query, token }) {
  await new Promise((r) => {
    setTimeout(r, RESPONSE_DELAY_MS);
  });
  const cleanPath = path.split('?')[0];
  for (const [m, pattern, handler, opts] of routes) {
    if (m !== method) continue;
    const match = cleanPath.match(pattern);
    if (!match) continue;
    const user = opts && opts.auth ? authUser(token) : null;
    const result = handler({ user, body: body || {}, query: query || {}, params: match.slice(1) });
    save();
    // Hand back copies so pages can never mutate the mock's state.
    return JSON.parse(JSON.stringify(result));
  }
  return fail(404, `No route for ${method} ${cleanPath}`, 'NOT_FOUND');
}
