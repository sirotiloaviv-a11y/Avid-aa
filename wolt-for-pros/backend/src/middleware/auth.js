const jwt = require('jsonwebtoken');
const config = require('../config');
const { prisma } = require('../db');
const { HttpError, asyncHandler } = require('./errors');

function signToken(user) {
  return jwt.sign({ sub: user.id, role: user.role }, config.jwtSecret, { expiresIn: config.jwtExpiresIn });
}

function verifyToken(token) {
  if (!token) throw new HttpError(401, 'Authentication required', 'UNAUTHENTICATED');
  try {
    return jwt.verify(token, config.jwtSecret);
  } catch {
    throw new HttpError(401, 'Invalid or expired token', 'UNAUTHENTICATED');
  }
}

// The role is read from the database rather than the token so a role change
// or a deleted account takes effect immediately.
const authenticate = asyncHandler(async (req, res, next) => {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;
  const payload = verifyToken(token);
  const user = await prisma.user.findUnique({ where: { id: payload.sub } });
  if (!user) throw new HttpError(401, 'Account no longer exists', 'UNAUTHENTICATED');
  req.user = user;
  next();
});

function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.user || !roles.includes(req.user.role)) {
      return next(new HttpError(403, `This action requires role: ${roles.join(' or ')}`, 'FORBIDDEN'));
    }
    return next();
  };
}

module.exports = { signToken, verifyToken, authenticate, requireRole };
