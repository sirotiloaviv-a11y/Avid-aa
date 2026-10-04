const http = require('http');
const config = require('./config');
const app = require('./app');
const { initSockets } = require('./sockets');
const { prisma } = require('./db');

const server = http.createServer(app);
const io = initSockets(server);

server.listen(config.port, () => {
  console.log(`Wolt for Pros API listening on http://localhost:${config.port}`);
  console.log(`Stripe: ${config.stripe.mockMode ? 'mock mode (no STRIPE_SECRET_KEY, top-ups credited directly)' : 'live checkout'}`);
  console.log(`Login: ${config.otpRequired ? `SMS code via ${config.twilio.enabled ? 'Twilio Verify' : 'dev codes in this log'}` : 'phone only (development)'}`);
});

process.on('unhandledRejection', (reason) => {
  console.error('[unhandledRejection]', reason);
});

async function shutdown(signal) {
  console.log(`${signal} received, shutting down`);
  io.close();
  server.close();
  await prisma.$disconnect();
  process.exit(0);
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
