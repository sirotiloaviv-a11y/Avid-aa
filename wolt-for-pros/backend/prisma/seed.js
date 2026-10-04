// Demo data around Tel Aviv. Safe to re-run: it wipes the tables first.
const crypto = require('crypto');
const { PrismaClient } = require('@prisma/client');
const { estimateFor, feeCents, generateCompletionCode } = require('../src/domain/pricing');
const { fromCents } = require('../src/domain/money');
const { underpriceReason } = require('../src/domain/fraud');

const prisma = new PrismaClient();
const FEE_RATE = Number(process.env.PLATFORM_FEE_RATE || 0.15);

const code = () => generateCompletionCode(crypto.randomInt);
const estimateCents = (type) => estimateFor(type).estimate * 100;
const electricianEstimate = () => estimateCents('electrician');

async function createPro({ name, phone, license, serviceType, lat, lng, deposit }) {
  return prisma.user.create({
    data: {
      name,
      phone,
      role: 'tradesperson',
      latitude: lat,
      longitude: lng,
      profile: { create: { licenseNumber: license, serviceType, status: 'active' } },
      wallet: {
        create: {
          balance: fromCents(deposit * 100),
          transactions: { create: { amount: fromCents(deposit * 100), type: 'deposit', note: 'Opening balance (seed)' } },
        },
      },
    },
    include: { wallet: true },
  });
}

async function main() {
  await prisma.review.deleteMany();
  await prisma.message.deleteMany();
  await prisma.jobPhoto.deleteMany();
  await prisma.walletTransaction.deleteMany();
  await prisma.job.deleteMany();
  await prisma.wallet.deleteMany();
  await prisma.tradespersonProfile.deleteMany();
  await prisma.user.deleteMany();

  await prisma.user.create({ data: { name: 'Noa (Admin)', phone: '0500000000', role: 'admin' } });
  const dana = await prisma.user.create({
    data: { name: 'Dana Levi', phone: '0501111111', role: 'client', latitude: 32.0853, longitude: 34.7818 },
  });
  const omer = await prisma.user.create({
    data: { name: 'Omer Cohen', phone: '0505555555', role: 'client', latitude: 32.0741, longitude: 34.7922 },
  });

  const yossi = await createPro({ name: 'Yossi the Electrician', phone: '0502222222', license: 'EL-48213', serviceType: 'electrician', lat: 32.0700, lng: 34.7700, deposit: 300 });
  // Deliberately low balance: shows the disabled Accept button and top-up prompt.
  await createPro({ name: 'Moshe Plumbing', phone: '0503333333', license: 'PL-11902', serviceType: 'plumber', lat: 32.0950, lng: 34.7850, deposit: 30 });
  await createPro({ name: 'Avi Fix-It', phone: '0504444444', license: 'HM-73001', serviceType: 'handyman', lat: 32.0600, lng: 34.7750, deposit: 500 });

  const openJobs = [
    { client: dana, serviceType: 'electrician', description: 'Breaker keeps tripping when the oven is on', address: 'Dizengoff St 120, Tel Aviv', lat: 32.0853, lng: 34.7818 },
    { client: omer, serviceType: 'electrician', description: 'Install two ceiling lights in the living room', address: 'Ibn Gabirol St 30, Tel Aviv', lat: 32.0790, lng: 34.7810 },
    { client: dana, serviceType: 'plumber', description: 'Kitchen sink is blocked and draining very slowly', address: 'Ben Yehuda St 80, Tel Aviv', lat: 32.0830, lng: 34.7700 },
    { client: omer, serviceType: 'plumber', description: 'Water heater (dud shemesh) leaking from the valve', address: 'Allenby St 50, Tel Aviv', lat: 32.0680, lng: 34.7710 },
    { client: dana, serviceType: 'handyman', description: 'Mount a 65" TV on a concrete wall', address: 'Rothschild Blvd 22, Tel Aviv', lat: 32.0635, lng: 34.7745 },
  ];
  for (const j of openJobs) {
    await prisma.job.create({
      data: {
        clientId: j.client.id,
        serviceType: j.serviceType,
        description: j.description,
        address: j.address,
        latitude: j.lat,
        longitude: j.lng,
        estimatedPrice: fromCents(estimateCents(j.serviceType)),
        completionCode: code(),
      },
    });
  }

  // Past jobs Dana rated, so Yossi starts with a real rating history. (History
  // only: their fees are not part of the seeded wallet ledger.)
  const pastReviews = [
    { rating: 5, comment: 'Arrived in 20 minutes and fixed the short. Very clean work.' },
    { rating: 5, comment: 'Explained everything and the price matched the estimate.' },
    { rating: 4, comment: 'Good job, a bit late.' },
  ];
  for (const [i, r] of pastReviews.entries()) {
    const done = new Date(Date.now() - (i + 2) * 7 * 24 * 60 * 60 * 1000);
    const past = await prisma.job.create({
      data: {
        clientId: dana.id,
        tradespersonId: yossi.id,
        serviceType: 'electrician',
        description: ['Replace kitchen light fixture', 'Install a dedicated AC circuit', 'Fix a dead wall socket'][i],
        latitude: 32.0853,
        longitude: 34.7818,
        estimatedPrice: fromCents(electricianEstimate()),
        finalPrice: fromCents(electricianEstimate()),
        platformFee: fromCents(feeCents(electricianEstimate(), FEE_RATE)),
        completionCode: code(),
        status: 'completed',
        completedAt: done,
        createdAt: done,
      },
    });
    await prisma.review.create({ data: { jobId: past.id, clientId: dana.id, tradespersonId: yossi.id, rating: r.rating, comment: r.comment, createdAt: done } });
  }
  const avg = pastReviews.reduce((s, r) => s + r.rating, 0) / pastReviews.length;
  await prisma.tradespersonProfile.update({
    where: { userId: yossi.id },
    data: { rating: Math.round(avg * 100) / 100, ratingCount: pastReviews.length },
  });

  // One open dispute: Yossi closed a ₪450 job at ₪150. His fee is still held.
  const est = estimateCents('electrician');
  const held = feeCents(est, FEE_RATE);
  const final = 150 * 100;
  const flaggedAt = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
  const flagged = await prisma.job.create({
    data: {
      clientId: omer.id,
      tradespersonId: yossi.id,
      serviceType: 'electrician',
      description: 'Replace a burnt power socket in the bedroom',
      address: 'Frishman St 40, Tel Aviv',
      latitude: 32.0805,
      longitude: 34.7735,
      estimatedPrice: fromCents(est),
      finalPrice: fromCents(final),
      platformFee: fromCents(held),
      completionCode: code(),
      status: 'flagged',
      flaggedAt,
      flagReason: underpriceReason(est, final),
      assignedAt: new Date(flaggedAt.getTime() - 2 * 60 * 60 * 1000),
      startedAt: new Date(flaggedAt.getTime() - 60 * 60 * 1000),
      completedAt: flaggedAt,
      createdAt: new Date(flaggedAt.getTime() - 3 * 60 * 60 * 1000),
    },
  });
  await prisma.wallet.update({
    where: { id: yossi.wallet.id },
    data: { balance: { decrement: fromCents(held) }, lockedBalance: { increment: fromCents(held) } },
  });
  await prisma.walletTransaction.create({
    data: { walletId: yossi.wallet.id, amount: fromCents(-held), type: 'fee_hold', jobId: flagged.id, note: 'Platform fee held on job acceptance' },
  });
  await prisma.tradespersonProfile.update({ where: { userId: yossi.id }, data: { fraudScore: 1 } });

  console.log('Seeded. Log in with:');
  console.log('  client       0501111111 (Dana)   0505555555 (Omer)');
  console.log('  electrician  0502222222 (Yossi, 1 open flag: one more gets him suspended)');
  console.log('  plumber      0503333333 (Moshe, ₪30 balance: too low to accept)');
  console.log('  handyman     0504444444 (Avi)');
  console.log('  admin        0500000000');
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
