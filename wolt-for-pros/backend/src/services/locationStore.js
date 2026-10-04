// Latest known position per tradesperson, kept in memory for live tracking.
// The users table holds a periodically persisted copy (see sockets/index.js),
// which is what a restarted server falls back to.
const lastLocations = new Map();

function set(userId, location) {
  lastLocations.set(userId, { ...location, at: location.at || new Date().toISOString() });
}

function get(userId) {
  return lastLocations.get(userId) || null;
}

module.exports = { set, get };
