// Thin holder for the Socket.io server so services can push events without
// importing the socket layer (and without a hard dependency in tests).
let io = null;

function setIo(server) {
  io = server;
}

function emit(room, event, payload) {
  if (io) io.to(room).emit(event, payload);
}

const rooms = {
  user: (userId) => `user:${userId}`,
  job: (jobId) => `job:${jobId}`,
  pros: (serviceType) => `pros:${serviceType}`,
  admins: () => 'admins',
};

module.exports = {
  setIo,
  rooms,
  toUser: (userId, event, payload) => emit(rooms.user(userId), event, payload),
  toJob: (jobId, event, payload) => emit(rooms.job(jobId), event, payload),
  toPros: (serviceType, event, payload) => emit(rooms.pros(serviceType), event, payload),
  toAdmins: (event, payload) => emit(rooms.admins(), event, payload),
};
