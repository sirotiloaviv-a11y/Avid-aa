// Escrow, settlement, code verification, fraud and admin rulings, run through
// the real services against an in-memory database.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadServices } = require('./helpers/loadServices');
const { serializeJob } = require('../src/serializers');

const { prisma, events, jobService, walletService, adminService } = loadServices();

let client;
let admin;
let pro;
let rival;

async function balances(userId) {
  const w = await prisma.wallet.findUnique({ where: { tradespersonId: userId } });
  return { available: Number(w.balance), locked: Number(w.lockedBalance) };
}

async function fund(userId, shekels) {
  await prisma.$transaction(async (tx) => {
    const w = await walletService.getOrCreateWallet(tx, userId);
    await walletService.addFunds(tx, { walletId: w.id, cents: shekels * 100, type: 'deposit' });
  });
}

const newJob = () => jobService.createJob(client, { serviceType: 'electrician', description: 'Breaker trips', latitude: 32.08, longitude: 34.78 });
const wrongCodeFor = (job) => (job.completionCode === '0000' ? '1111' : '0000');
const proUser = (id, name, license) => prisma.user.create({
  data: { name, phone: `05${license}`, role: 'tradesperson', profile: { create: { licenseNumber: license, serviceType: 'electrician', status: 'active' } }, wallet: { create: {} } },
});

test.beforeEach(async () => {
  prisma._reset();
  events.length = 0;
  client = await prisma.user.create({ data: { name: 'Dana', phone: '0501111111', role: 'client' } });
  admin = await prisma.user.create({ data: { name: 'Noa', phone: '0500000000', role: 'admin' } });
  pro = await proUser('pro', 'Yossi', '00000001');
  rival = await proUser('rival', 'Eli', '00000002');
});

test('accept is refused when available balance is below the 15% fee, and nothing changes', async () => {
  await fund(pro.id, 50);
  const job = await newJob();
  await assert.rejects(jobService.acceptJob(pro, job.id), { code: 'INSUFFICIENT_BALANCE' });
  assert.deepEqual(await balances(pro.id), { available: 50, locked: 0 });
  assert.equal((await prisma.job.findUnique({ where: { id: job.id } })).status, 'requested');
});

test('accept moves the fee from available to locked and records a fee_hold', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  assert.deepEqual(await balances(pro.id), { available: 232.5, locked: 67.5 });
  const txs = await prisma.walletTransaction.findMany({ where: { jobId: job.id } });
  assert.deepEqual(txs.map((t) => [t.type, Number(t.amount)]), [['fee_hold', -67.5]]);
  assert.ok(events.some((e) => e.event === 'job:taken'));
});

test('a job cannot be accepted twice, and the second pro is not charged', async () => {
  await fund(pro.id, 300);
  await fund(rival.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  await assert.rejects(jobService.acceptJob(rival, job.id), { code: 'JOB_NOT_AVAILABLE' });
  assert.deepEqual(await balances(rival.id), { available: 300, locked: 0 });
});

test('a pro can hold only one active job', async () => {
  await fund(pro.id, 500);
  const a = await newJob();
  const b = await newJob();
  await jobService.acceptJob(pro, a.id);
  await assert.rejects(jobService.acceptJob(pro, b.id), { code: 'ALREADY_ON_JOB' });
});

test('the completion code is never serialized for the tradesperson', async () => {
  const job = await newJob();
  assert.equal(serializeJob(job, pro).completionCode, undefined);
  assert.equal(serializeJob(job, null).completionCode, undefined);
  assert.match(serializeJob(job, client).completionCode, /^\d{4}$/);
});

test('a wrong code is rejected and counted; the right code settles the fee on the final price', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  await assert.rejects(
    jobService.verifyAndComplete(pro, job.id, { completionCode: wrongCodeFor(job), finalPrice: 500 }),
    { code: 'WRONG_CODE' },
  );
  assert.equal((await prisma.job.findUnique({ where: { id: job.id } })).codeAttempts, 1);
  assert.deepEqual(await balances(pro.id), { available: 232.5, locked: 67.5 }, 'wrong code moves no money');

  const result = await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 500 });
  assert.equal(result.outcome, 'completed');
  assert.equal(Number(result.job.platformFee), 75);
  // 300 - 75 fee on ₪500
  assert.deepEqual(await balances(pro.id), { available: 225, locked: 0 });
});

test('a final fee below the hold releases the difference as a refund', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 400 });
  assert.deepEqual(await balances(pro.id), { available: 240, locked: 0 });
  const txs = await prisma.walletTransaction.findMany({ where: { jobId: job.id } });
  assert.deepEqual(txs.map((t) => [t.type, Number(t.amount)]), [['fee_hold', -67.5], ['fee_deduction', -60], ['refund', 7.5]]);
});

test('five wrong codes lock the job', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  for (let i = 0; i < 5; i += 1) {
    await assert.rejects(jobService.verifyAndComplete(pro, job.id, { completionCode: wrongCodeFor(job), finalPrice: 450 }), { code: 'WRONG_CODE' });
  }
  await assert.rejects(jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 450 }), { code: 'CODE_LOCKED' });
});

test('cancelling releases the hold: client cancels the job, pro returns it to the pool', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  await jobService.cancelJob(pro, job.id, 'flat tyre');
  let row = await prisma.job.findUnique({ where: { id: job.id } });
  assert.equal(row.status, 'requested');
  assert.equal(row.tradespersonId, null);
  assert.deepEqual(await balances(pro.id), { available: 300, locked: 0 });

  await jobService.acceptJob(pro, job.id);
  await jobService.cancelJob(client, job.id);
  row = await prisma.job.findUnique({ where: { id: job.id } });
  assert.equal(row.status, 'cancelled');
  assert.deepEqual(await balances(pro.id), { available: 300, locked: 0 });
  await assert.rejects(jobService.cancelJob(client, job.id), { code: 'INVALID_STATUS' });
});

test('an underpriced close is flagged with the fee kept locked; the second flag suspends', async () => {
  await fund(pro.id, 500);
  const first = await newJob();
  await jobService.acceptJob(pro, first.id);
  const r1 = await jobService.verifyAndComplete(pro, first.id, { completionCode: first.completionCode, finalPrice: 150 });
  assert.equal(r1.outcome, 'flagged');
  assert.equal(r1.suspended, false);
  assert.deepEqual(await balances(pro.id), { available: 432.5, locked: 67.5 });
  assert.ok(events.some((e) => e.room === 'admins' && e.event === 'flagged:new'));

  const second = await newJob();
  await jobService.acceptJob(pro, second.id);
  const r2 = await jobService.verifyAndComplete(pro, second.id, { completionCode: second.completionCode, finalPrice: 100 });
  assert.equal(r2.suspended, true);
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId: pro.id } });
  assert.equal(profile.status, 'suspended');
  assert.equal(profile.fraudScore, 2);

  const third = await newJob();
  await assert.rejects(jobService.acceptJob(pro, third.id), { code: 'ACCOUNT_SUSPENDED' });
});

test('exactly 50% of the estimate is not flagged', async () => {
  await fund(pro.id, 300);
  const job = await newJob();
  await jobService.acceptJob(pro, job.id);
  const r = await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: 225 });
  assert.equal(r.outcome, 'completed');
});

test('admin rulings settle the held fee: approve on final, reject on estimate, void releases', async () => {
  await fund(pro.id, 1000);
  const flag = async (finalPrice) => {
    const job = await newJob();
    await jobService.acceptJob(pro, job.id);
    await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice });
    await prisma.tradespersonProfile.update({ where: { userId: pro.id }, data: { status: 'active' } });
    return job;
  };

  const approved = await flag(150);
  await adminService.resolveFlaggedJob(admin, { jobId: approved.id, action: 'approve' });
  assert.deepEqual(await balances(pro.id), { available: 977.5, locked: 0 }, 'fee on ₪150 = ₪22.50');

  const rejected = await flag(150);
  await adminService.resolveFlaggedJob(admin, { jobId: rejected.id, action: 'charge_estimate' });
  assert.deepEqual(await balances(pro.id), { available: 910, locked: 0 }, 'fee on ₪450 = ₪67.50');

  const voided = await flag(50);
  await adminService.resolveFlaggedJob(admin, { jobId: voided.id, action: 'void' });
  assert.deepEqual(await balances(pro.id), { available: 910, locked: 0 });
  assert.equal((await prisma.job.findUnique({ where: { id: voided.id } })).status, 'cancelled');

  await assert.rejects(adminService.resolveFlaggedJob(admin, { jobId: voided.id, action: 'approve' }), { code: 'INVALID_STATUS' });
  const pros = await adminService.listTradespeople();
  assert.equal(pros.find((p) => p.id === pro.id).flagsInWindow, 2, 'an approved flag stops counting');
});

test('the ledger reconciles: deposits + adjustments + fee deductions = total funds', async () => {
  await fund(pro.id, 400);
  for (const price of [500, 150]) {
    const job = await newJob();
    await jobService.acceptJob(pro, job.id);
    await jobService.verifyAndComplete(pro, job.id, { completionCode: job.completionCode, finalPrice: price });
  }
  await adminService.adjustWallet(pro.id, { amount: -20, note: 'chargeback' }, admin);
  const wallet = await prisma.wallet.findUnique({ where: { tradespersonId: pro.id } });
  const txs = await prisma.walletTransaction.findMany({ where: { walletId: wallet.id } });
  const moved = txs.filter((t) => ['deposit', 'adjustment', 'fee_deduction'].includes(t.type)).reduce((s, t) => s + Math.round(Number(t.amount) * 100), 0);
  const total = Math.round((Number(wallet.balance) + Number(wallet.lockedBalance)) * 100);
  assert.equal(moved, total);
});

test('a Stripe session credits the wallet once, however often it is delivered', async () => {
  const wallet = await prisma.wallet.findUnique({ where: { tradespersonId: pro.id } });
  const first = await walletService.creditStripeDeposit({ walletId: wallet.id, cents: 20000, sessionId: 'cs_test_1' });
  const replay = await walletService.creditStripeDeposit({ walletId: wallet.id, cents: 20000, sessionId: 'cs_test_1' });
  assert.equal(first.credited, true);
  assert.equal(replay.credited, false);
  assert.deepEqual(await balances(pro.id), { available: 200, locked: 0 });
});
