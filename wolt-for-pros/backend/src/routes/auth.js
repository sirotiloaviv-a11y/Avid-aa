const express = require('express');
const { z } = require('zod');
const { prisma } = require('../db');
const { asyncHandler, parse, HttpError } = require('../middleware/errors');
const { authenticate, signToken } = require('../middleware/auth');
const { limits } = require('../middleware/rateLimit');
const smsService = require('../services/smsService');
const { publicUser, serializeProfile } = require('../serializers');

const router = express.Router();

const phone = z.string().trim().regex(/^\+?[0-9]{9,15}$/, 'Phone must be 9-15 digits');
const otpCode = z.string().trim().regex(/^\d{4,8}$/, 'The code is 4-8 digits').optional();

const registerSchema = z.discriminatedUnion('role', [
  z.object({ role: z.literal('client'), name: z.string().trim().min(2).max(80), phone, otpCode }),
  z.object({
    role: z.literal('tradesperson'),
    name: z.string().trim().min(2).max(80),
    phone,
    otpCode,
    licenseNumber: z.string().trim().min(3).max(40),
    serviceType: z.enum(['electrician', 'plumber', 'handyman']),
  }),
]);

// Step 1 when OTP_REQUIRED=true: text a one-time code to the phone.
router.post('/otp/request', limits.auth, limits.otpPerPhone, asyncHandler(async (req, res) => {
  const body = parse(z.object({ phone }), req.body);
  const result = await smsService.sendCode(body.phone);
  res.json(result);
}));

// Step 2: log in. With OTP_REQUIRED=true the code from step 1 is required;
// otherwise (development) the phone number alone signs in.
router.post('/login', limits.auth, asyncHandler(async (req, res) => {
  const body = parse(z.object({ phone, otpCode }), req.body);
  const user = await prisma.user.findUnique({ where: { phone: body.phone }, include: { profile: true } });
  // Verify before revealing whether the number has an account.
  await smsService.assertVerified(body.phone, body.otpCode);
  if (!user) throw new HttpError(404, 'No account with this phone number. Register first.', 'NO_ACCOUNT');
  res.json({ token: signToken(user), user: publicUser(user), profile: serializeProfile(user.profile) });
}));

router.post('/register', limits.auth, asyncHandler(async (req, res) => {
  const body = parse(registerSchema, req.body);
  await smsService.assertVerified(body.phone, body.otpCode);
  const exists = await prisma.user.findUnique({ where: { phone: body.phone } });
  if (exists) throw new HttpError(409, 'This phone number is already registered', 'PHONE_TAKEN');

  if (body.role === 'tradesperson') {
    const licenseTaken = await prisma.tradespersonProfile.findUnique({ where: { licenseNumber: body.licenseNumber } });
    if (licenseTaken) throw new HttpError(409, 'This license number is already registered', 'LICENSE_TAKEN');
  }

  const user = await prisma.user.create({
    data: {
      name: body.name,
      phone: body.phone,
      role: body.role,
      ...(body.role === 'tradesperson' && {
        profile: { create: { licenseNumber: body.licenseNumber, serviceType: body.serviceType, status: 'inactive' } },
        wallet: { create: {} },
      }),
    },
    include: { profile: true },
  });
  res.status(201).json({ token: signToken(user), user: publicUser(user), profile: serializeProfile(user.profile) });
}));

router.get('/me', authenticate, asyncHandler(async (req, res) => {
  const profile = await prisma.tradespersonProfile.findUnique({ where: { userId: req.user.id } });
  res.json({ user: publicUser(req.user), profile: serializeProfile(profile) });
}));

module.exports = router;
