const test = require('node:test');
const assert = require('node:assert/strict');
const { toE164, maskPhone } = require('../src/domain/phone');
const { rateLimit, MemoryStore } = require('../src/middleware/rateLimit');
const smsService = require('../src/services/smsService');

test('phone numbers normalise to E.164', () => {
  assert.equal(toE164('0501234567'), '+972501234567');
  assert.equal(toE164('050-123-4567'), '+972501234567');
  assert.equal(toE164('+972501234567'), '+972501234567');
  assert.equal(toE164('00972501234567'), '+972501234567');
  assert.equal(toE164('972501234567'), '+972501234567');
  assert.equal(toE164('+14155550123'), '+14155550123');
  assert.throws(() => toE164(''));
  assert.throws(() => toE164('12'));
  assert.equal(maskPhone('+972501234567'), '+97250***4567');
});

function run(middleware, req) {
  const headers = {};
  const res = { setHeader: (k, v) => { headers[k] = v; } };
  return new Promise((resolve) => {
    middleware(req, res, (err) => resolve({ err, headers }));
  });
}

test('rate limiter allows max requests per window, then answers 429', async () => {
  const limiter = rateLimit({ name: 't', windowMs: 60000, max: 3, store: new MemoryStore() });
  const req = { ip: '1.2.3.4' };
  for (let i = 0; i < 3; i += 1) assert.equal((await run(limiter, req)).err, undefined);
  const { err, headers } = await run(limiter, req);
  assert.equal(err.status, 429);
  assert.equal(err.code, 'RATE_LIMITED');
  assert.ok(Number(headers['Retry-After']) > 0);
  assert.equal((await run(limiter, { ip: '5.6.7.8' })).err, undefined, 'other clients are unaffected');
});

test('rate limiter window resets', async () => {
  const limiter = rateLimit({ name: 'w', windowMs: 30, max: 1, store: new MemoryStore() });
  assert.equal((await run(limiter, { ip: 'a' })).err, undefined);
  assert.equal((await run(limiter, { ip: 'a' })).err.status, 429);
  await new Promise((r) => {
    setTimeout(r, 40);
  });
  assert.equal((await run(limiter, { ip: 'a' })).err, undefined);
});

test('rate limiter fails open when its store breaks', async () => {
  const broken = { increment: async () => { throw new Error('redis down'); } };
  const limiter = rateLimit({ name: 'b', windowMs: 1000, max: 1, store: broken });
  const originalError = console.error;
  console.error = () => {};
  try {
    assert.equal((await run(limiter, { ip: 'a' })).err, undefined);
  } finally {
    console.error = originalError;
  }
});

test('dev SMS codes verify once, reject wrong or longer codes', async () => {
  smsService._resetDevCodes();
  const originalLog = console.log;
  console.log = () => {};
  try {
    const { devCode } = await smsService.sendCode('0501234567');
    assert.match(devCode, /^\d{6}$/);
    assert.equal(await smsService.checkCode('0501234567', devCode === '000000' ? '111111' : '000000'), false);
    assert.equal(await smsService.checkCode('0501234567', `${devCode}1`), false);
    assert.equal(await smsService.checkCode('+972501234567', devCode), true, 'same number in another format');
    assert.equal(await smsService.checkCode('0501234567', devCode), false, 'codes are single-use');
  } finally {
    console.log = originalLog;
  }
});
