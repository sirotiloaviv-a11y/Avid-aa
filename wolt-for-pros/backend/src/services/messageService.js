const { prisma } = require('../db');
const { HttpError } = require('../middleware/errors');
const { ACTIVE_JOB_STATUSES, MAX_MESSAGE_LENGTH } = require('../domain/constants');
const realtime = require('../realtime');

function serializeMessage(message, job) {
  return {
    id: message.id,
    jobId: message.jobId,
    senderId: message.senderId,
    senderRole: message.senderId === job.clientId ? 'client' : 'tradesperson',
    senderName: message.sender ? message.sender.name : undefined,
    body: message.body,
    createdAt: message.createdAt,
  };
}

async function loadJobFor(user, jobId) {
  const job = await prisma.job.findUnique({ where: { id: jobId } });
  if (!job) throw new HttpError(404, 'Job not found', 'JOB_NOT_FOUND');
  const participant = job.clientId === user.id || (job.tradespersonId && job.tradespersonId === user.id);
  if (!participant && user.role !== 'admin') throw new HttpError(403, 'You are not part of this job', 'FORBIDDEN');
  return { job, participant };
}

// History is readable by both parties (and admins, for disputes) at any time.
async function listMessages(user, jobId) {
  const { job } = await loadJobFor(user, jobId);
  const messages = await prisma.message.findMany({
    where: { jobId },
    include: { sender: true },
    orderBy: { createdAt: 'asc' },
    take: 500,
  });
  return messages.map((m) => serializeMessage(m, job));
}

// Only the client and the assigned tradesperson can write, and only while
// the job is in flight.
async function sendMessage(user, jobId, rawBody) {
  const { job, participant } = await loadJobFor(user, jobId);
  if (!participant) throw new HttpError(403, 'Only the client and the assigned pro can chat', 'FORBIDDEN');
  if (!ACTIVE_JOB_STATUSES.includes(job.status)) {
    throw new HttpError(409, 'Chat is open only while a pro is assigned to the job', 'CHAT_CLOSED');
  }
  const body = String(rawBody || '').trim();
  if (!body) throw new HttpError(400, 'Message is empty', 'EMPTY_MESSAGE');
  if (body.length > MAX_MESSAGE_LENGTH) {
    throw new HttpError(400, `Messages can be up to ${MAX_MESSAGE_LENGTH} characters`, 'MESSAGE_TOO_LONG');
  }

  const message = await prisma.message.create({ data: { jobId, senderId: user.id, body }, include: { sender: true } });
  const payload = serializeMessage(message, job);
  // One emit to both personal rooms; Socket.io delivers once per socket.
  realtime.toRooms([realtime.rooms.user(job.clientId), realtime.rooms.user(job.tradespersonId)], 'message:new', payload);
  return payload;
}

module.exports = { listMessages, sendMessage, serializeMessage };
