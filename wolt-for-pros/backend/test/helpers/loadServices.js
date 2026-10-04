// Loads the services with the in-memory fake in place of src/db.js, and a
// recording stub in place of the Socket.io server.
const path = require('path');
const { createFakePrisma } = require('./fakePrisma');

function loadServices() {
  const prisma = createFakePrisma();
  const dbPath = path.resolve(__dirname, '../../src/db.js');
  require.cache[dbPath] = /** @type {any} */ ({ id: dbPath, filename: dbPath, loaded: true, exports: { prisma } });

  const realtime = require('../../src/realtime');
  const events = [];
  realtime.setIo({ to: (room) => ({ emit: (event, payload) => events.push({ room, event, payload }) }) });

  return {
    prisma,
    events,
    jobService: require('../../src/services/jobService'),
    walletService: require('../../src/services/walletService'),
    adminService: require('../../src/services/adminService'),
  };
}

module.exports = { loadServices };
