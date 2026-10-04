const ROLES = ['client', 'tradesperson', 'admin'];
const SERVICE_TYPES = ['electrician', 'plumber', 'handyman'];
const PROFILE_STATUSES = ['active', 'inactive', 'suspended'];
const JOB_STATUSES = ['requested', 'assigned', 'in_progress', 'completed', 'cancelled', 'flagged'];
const ACTIVE_JOB_STATUSES = ['assigned', 'in_progress'];
const TRANSACTION_TYPES = ['deposit', 'fee_hold', 'fee_deduction', 'refund', 'adjustment'];
const RESOLUTIONS = ['approved', 'charged_estimate', 'voided'];

// Wallet top-ups, in shekels.
const TOP_UP_PRESETS = [100, 200, 500];
const TOP_UP_MIN = 20;
const TOP_UP_MAX = 5000;

// Wrong completion-code guesses allowed before the job locks for review.
const MAX_CODE_ATTEMPTS = 5;

// Problem photos per job, and the largest accepted upload.
const MAX_JOB_PHOTOS = 5;
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

// Chat
const MAX_MESSAGE_LENGTH = 1000;

// How far the job radar looks, in kilometres.
const DEFAULT_RADAR_RADIUS_KM = 25;

module.exports = {
  ROLES,
  SERVICE_TYPES,
  PROFILE_STATUSES,
  JOB_STATUSES,
  ACTIVE_JOB_STATUSES,
  TRANSACTION_TYPES,
  RESOLUTIONS,
  TOP_UP_PRESETS,
  TOP_UP_MIN,
  TOP_UP_MAX,
  MAX_CODE_ATTEMPTS,
  DEFAULT_RADAR_RADIUS_KM,
  MAX_JOB_PHOTOS,
  MAX_UPLOAD_BYTES,
  MAX_MESSAGE_LENGTH,
};
