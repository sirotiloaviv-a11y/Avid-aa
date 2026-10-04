// Ratings, chat and problem photos, through the real services against the
// in-memory database.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadServices } = require('./helpers/loadServices');
const { serializeJob } = require('../src/serializers');
const { detectImageType, isAllowedPhotoUrl } = require('../src/domain/media');

const { prisma, events, jobService, walletService } = loadServices();
const reviewService = require('../src/services/reviewService');
const messageService = require('../src/services/messageService');
const config = require('../src/config');
const storageService = require('../src/services/storageService');

let client;
let stranger;
let admin;
let pro;

async function activeJob(photos = []) {
  await prisma.$transaction(async (tx) => {
    const w = await walletService.getOrCreateWallet(tx, pro.id);
    await walletService.addFunds(tx, { walletId: w.id, cents: 50000, type: 'deposit' });
  });
  const job = await jobService.createJob(client, { serviceType: 'electrician', description: 'Burnt socket', latitude: 32.08, longitude: 34.78, photos });
  await jobService.acceptJob(pro, job.id);
  return job;
}

async function completedJob() {
  const job = await activeJob();
  await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 450 });
  return job;
}

test.beforeEach(async () => {
  prisma._reset();
  events.length = 0;
  client = await prisma.user.create({ data: { name: 'Dana', phone: '0501111111', role: 'client' } });
  stranger = await prisma.user.create({ data: { name: 'Omer', phone: '0505555555', role: 'client' } });
  admin = await prisma.user.create({ data: { name: 'Noa', phone: '0500000000', role: 'admin' } });
  pro = await prisma.user.create({
    data: { name: 'Yossi', phone: '0502222222', role: 'tradesperson', profile: { create: { licenseNumber: 'EL-1', serviceType: 'electrician', status: 'active' } }, wallet: { create: {} } },
  });
});

// ---- ratings ---------------------------------------------------------------

test('a client rates a completed job once, and the pro average updates', async () => {
  const first = await completedJob();
  const r1 = await reviewService.createReview(client, first.id, { rating: 5, comment: 'Great' });
  assert.equal(r1.profile.rating, 5);
  assert.equal(r1.profile.ratingCount, 1);
  await assert.rejects(reviewService.createReview(client, first.id, { rating: 1 }), { code: 'ALREADY_REVIEWED' });

  const second = await completedJob();
  const r2 = await reviewService.createReview(client, second.id, { rating: 4 });
  assert.equal(r2.profile.rating, 4.5);
  assert.equal(r2.profile.ratingCount, 2);

  const third = await completedJob();
  const r3 = await reviewService.createReview(client, third.id, { rating: 4 });
  assert.equal(r3.profile.rating, 4.33, 'rounded to 2 decimals');
  assert.ok(events.some((e) => e.room === `user:${pro.id}` && e.event === 'review:new'));

  const loaded = await jobService.loadJob(prisma, third.id);
  assert.deepEqual(serializeJob(loaded, client).review.rating, 4);
  assert.equal(serializeJob(loaded, client).tradesperson.rating, 4.33);
});

test('only the booking client can rate, and only after completion', async () => {
  const job = await activeJob();
  await assert.rejects(reviewService.createReview(client, job.id, { rating: 5 }), { code: 'NOT_COMPLETED' });
  await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 450 });
  await assert.rejects(reviewService.createReview(stranger, job.id, { rating: 1 }), { code: 'FORBIDDEN' });
  await assert.rejects(reviewService.createReview(client, 'nope', { rating: 5 }), { code: 'JOB_NOT_FOUND' });
});

test('a flagged job cannot be rated until it is resolved', async () => {
  const job = await activeJob();
  await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 100 });
  await assert.rejects(reviewService.createReview(client, job.id, { rating: 5 }), { code: 'NOT_COMPLETED' });
});

// ---- chat ------------------------------------------------------------------

test('client and assigned pro can chat on an active job; both receive it', async () => {
  const job = await activeJob();
  const m1 = await messageService.sendMessage(client, job.id, '  The gate code is 1234  ');
  assert.equal(m1.body, 'The gate code is 1234');
  assert.equal(m1.senderRole, 'client');
  assert.equal(m1.senderName, 'Dana');
  const m2 = await messageService.sendMessage(pro, job.id, 'On my way');
  assert.equal(m2.senderRole, 'tradesperson');

  const history = await messageService.listMessages(pro, job.id);
  assert.deepEqual(history.map((m) => m.body), ['The gate code is 1234', 'On my way']);
  assert.equal((await messageService.listMessages(admin, job.id)).length, 2, 'admins can read for disputes');

  const delivered = events.filter((e) => e.event === 'message:new');
  assert.equal(delivered.length, 2);
  assert.deepEqual(delivered[0].room, [`user:${client.id}`, `user:${pro.id}`]);
});

test('chat rejects outsiders, admins writing, empty or long messages, and closed jobs', async () => {
  const job = await activeJob();
  await assert.rejects(messageService.sendMessage(stranger, job.id, 'hi'), { code: 'FORBIDDEN' });
  await assert.rejects(messageService.listMessages(stranger, job.id), { code: 'FORBIDDEN' });
  await assert.rejects(messageService.sendMessage(admin, job.id, 'hi'), { code: 'FORBIDDEN' });
  await assert.rejects(messageService.sendMessage(client, job.id, '   '), { code: 'EMPTY_MESSAGE' });
  await assert.rejects(messageService.sendMessage(client, job.id, 'x'.repeat(1001)), { code: 'MESSAGE_TOO_LONG' });

  await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 450 });
  await assert.rejects(messageService.sendMessage(client, job.id, 'thanks!'), { code: 'CHAT_CLOSED' });

  const open = await jobService.createJob(client, { serviceType: 'electrician', description: 'Lights', latitude: 32.08, longitude: 34.78 });
  await assert.rejects(messageService.sendMessage(client, open.id, 'anyone?'), { code: 'CHAT_CLOSED' });
});

// ---- photos ----------------------------------------------------------------

test('job photos are stored in order and shown to the pro on the radar', async () => {
  const photos = ['/uploads/0123456789abcdef0123456789abcdef.jpg', 'https://images.example.com/socket.png'];
  const job = await jobService.createJob(client, { serviceType: 'electrician', description: 'Burnt socket', latitude: 32.08, longitude: 34.78, photos });
  assert.deepEqual(serializeJob(job, client).photos, photos);
  const radar = await jobService.nearbyJobs(pro, { lat: 32.07, lng: 34.77 });
  assert.deepEqual(radar.find((j) => j.id === job.id).photos, photos);
});

test('photo URLs must be our uploads or https', () => {
  assert.equal(isAllowedPhotoUrl('/uploads/0123456789abcdef0123456789abcdef.webp'), true);
  assert.equal(isAllowedPhotoUrl('https://cdn.example.com/a.jpg'), true);
  assert.equal(isAllowedPhotoUrl('http://cdn.example.com/a.jpg'), false);
  assert.equal(isAllowedPhotoUrl('javascript:alert(1)'), false);
  assert.equal(isAllowedPhotoUrl('data:image/png;base64,AAAA'), false);
  assert.equal(isAllowedPhotoUrl('/uploads/../../etc/passwd'), false);
  assert.equal(isAllowedPhotoUrl(`https://x.com/${'a'.repeat(500)}`), false);
});

test('uploads are typed by their bytes and saved under random names', async () => {
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0x0d]);
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0x10]);
  const webp = Buffer.concat([Buffer.from('RIFF'), Buffer.from([0, 0, 0, 0]), Buffer.from('WEBPVP8 ')]);
  assert.equal(detectImageType(png).ext, 'png');
  assert.equal(detectImageType(jpeg).ext, 'jpg');
  assert.equal(detectImageType(webp).ext, 'webp');
  assert.equal(detectImageType(Buffer.from('<svg onload=alert(1)>')), null);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wfp-uploads-'));
  const original = config.uploadDir;
  config.uploadDir = dir;
  try {
    const saved = await storageService.saveImage(png);
    assert.match(saved.url, /^\/uploads\/[a-f0-9]{32}\.png$/);
    assert.ok(isAllowedPhotoUrl(saved.url));
    assert.ok(fs.existsSync(path.join(dir, path.basename(saved.url))));
    await assert.rejects(storageService.saveImage(Buffer.from('GIF89a....')), { code: 'UNSUPPORTED_IMAGE' });
    await assert.rejects(storageService.saveImage(Buffer.alloc(0)), { code: 'EMPTY_UPLOAD' });
  } finally {
    config.uploadDir = original;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
