// Demo engine (lib/demo/mockServer.js): the seeded scenario and the same
// money rules as the backend. Run with `npm test` (Node 22+).
import test from 'node:test';
import assert from 'node:assert/strict';
import { mockRequest, demoSocket, toggleDemoDrive, isDemoDriving, resetDemo, DEMO_ACTIVE_JOB_ID } from '../lib/demo/mockServer.js';

const req = (method, path, token, body, query) => mockRequest({ method, path, token, body, query });
const login = async (phone) => (await req('POST', '/api/auth/login', null, { phone })).token;
const PRO = '0502222222';
const CLIENT = '0501111111';
const ADMIN = '0500000000';

test.beforeEach(() => resetDemo());

test('seed: Yossi Cohen, ₪350 available / ₪50 locked, on the outlet job', async () => {
  const me = await req('GET', '/api/pros/me', await login(PRO));
  assert.equal(me.user.name, 'Yossi Cohen');
  assert.equal(me.profile.status, 'active');
  assert.deepEqual([me.wallet.balance, me.wallet.lockedBalance], [350, 50]);
  assert.equal(me.activeJob.id, DEMO_ACTIVE_JOB_ID);
  assert.equal(me.activeJob.estimatedPrice, 400);
  assert.equal(me.activeJob.platformFee, 60);
  assert.equal(me.activeJob.completionCode, undefined, 'the pro never sees the code');
  const asClient = await req('GET', `/api/jobs/${DEMO_ACTIVE_JOB_ID}`, await login(CLIENT));
  assert.equal(asClient.job.completionCode, '4829');
});

test('top up ₪100 credits the wallet and logs a deposit', async () => {
  const pro = await login(PRO);
  await req('POST', '/api/wallet/deposit', pro, { amount: 100 });
  const bal = await req('GET', '/api/wallet/balance', pro);
  assert.equal(bal.wallet.balance, 450);
  assert.deepEqual([bal.transactions[0].type, bal.transactions[0].amount], ['deposit', 100]);
});

test('code 4829 closes the job and settles the fee; wrong codes do not', async () => {
  const pro = await login(PRO);
  await assert.rejects(
    req('POST', `/api/jobs/${DEMO_ACTIVE_JOB_ID}/verify-and-complete`, pro, { completionCode: '1111', finalPrice: 400 }),
    { code: 'WRONG_CODE' },
  );
  const res = await req('POST', `/api/jobs/${DEMO_ACTIVE_JOB_ID}/verify-and-complete`, pro, { completionCode: '4829', finalPrice: 400 });
  assert.equal(res.outcome, 'completed');
  const bal = await req('GET', '/api/wallet/balance', pro);
  // ₪50 locked released, ₪60 fee charged: 350 + 50 - 60
  assert.deepEqual([bal.wallet.balance, bal.wallet.lockedBalance], [340, 0]);
  assert.deepEqual([bal.transactions[0].type, bal.transactions[0].amount], ['fee_deduction', -60]);
});

test('an underpriced close is flagged and shows up for the admin', async () => {
  const pro = await login(PRO);
  const res = await req('POST', `/api/jobs/${DEMO_ACTIVE_JOB_ID}/verify-and-complete`, pro, { completionCode: '4829', finalPrice: 150 });
  assert.equal(res.outcome, 'flagged');
  const open = await req('GET', '/api/admin/flagged-jobs', await login(ADMIN), undefined, { state: 'open' });
  assert.equal(open.jobs.length, 2);
});

test('accepting needs the fee in the available balance', async () => {
  const pro = await login(PRO);
  await req('POST', `/api/jobs/${DEMO_ACTIVE_JOB_ID}/verify-and-complete`, pro, { completionCode: '4829', finalPrice: 400 });
  const radar = await req('GET', '/api/jobs/nearby', pro, undefined, { lat: 32.07, lng: 34.77 });
  assert.ok(radar.jobs.length > 0 && radar.jobs.every((j) => j.canAfford));
  await req('POST', `/api/jobs/${radar.jobs[0].id}/accept`, pro, {});
  const bal = await req('GET', '/api/wallet/balance', pro);
  assert.deepEqual([bal.wallet.balance, bal.wallet.lockedBalance], [340 - 67.5, 67.5]);

  const moshe = await login('0503333333');
  const jobs = (await req('GET', '/api/jobs/nearby', moshe, undefined, {})).jobs;
  assert.equal(jobs[0].canAfford, false);
  await assert.rejects(req('POST', `/api/jobs/${jobs[0].id}/accept`, moshe, {}), { code: 'INSUFFICIENT_BALANCE' });
});

test('admin: approve charges on ₪150, reject charges on the ₪400 estimate', async () => {
  const admin = await login(ADMIN);
  const [flagged] = (await req('GET', '/api/admin/flagged-jobs', admin, undefined, { state: 'open' })).jobs;
  assert.equal(flagged.flagReason, 'Unusual low price ₪150 vs ₪400 estimate');
  await req('POST', '/api/admin/flagged-jobs', admin, { jobId: flagged.id, action: 'charge_estimate' });
  const avi = (await req('GET', '/api/admin/tradespeople', admin)).tradespeople.find((p) => p.name === 'Avi Mizrahi');
  assert.deepEqual([avi.wallet.balance, avi.wallet.lockedBalance], [200, 0]);

  resetDemo();
  const again = (await req('GET', '/api/admin/flagged-jobs', admin, undefined, { state: 'open' })).jobs[0];
  await req('POST', '/api/admin/flagged-jobs', admin, { jobId: again.id, action: 'approve' });
  const avi2 = (await req('GET', '/api/admin/tradespeople', admin)).tradespeople.find((p) => p.name === 'Avi Mizrahi');
  assert.deepEqual([avi2.wallet.balance, avi2.wallet.lockedBalance], [237.5, 0]);
});

test('the driver simulation moves the pro toward the client', async () => {
  const points = [];
  const onLoc = (l) => points.push(l);
  demoSocket.on('pro:location', onLoc);
  try {
    assert.equal(toggleDemoDrive(DEMO_ACTIVE_JOB_ID), true);
    await new Promise((r) => { setTimeout(r, 2300); });
    assert.equal(isDemoDriving(DEMO_ACTIVE_JOB_ID), true);
    toggleDemoDrive(DEMO_ACTIVE_JOB_ID);
    assert.equal(isDemoDriving(DEMO_ACTIVE_JOB_ID), false);
    assert.ok(points.length >= 2);
    assert.ok(points.at(-1).distanceKm < points[0].distanceKm, 'getting closer');
  } finally {
    demoSocket.off('pro:location', onLoc);
  }
});

test('unknown routes and bad tokens fail like the real API', async () => {
  await assert.rejects(req('GET', '/api/nope', null), { status: 404 });
  await assert.rejects(req('GET', '/api/auth/me', 'bogus'), { status: 401 });
  const otp = await req('POST', '/api/auth/otp/request', null, { phone: CLIENT });
  assert.equal(otp.sent, true);
});
