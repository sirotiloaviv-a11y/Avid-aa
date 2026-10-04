// Stores uploaded images and returns the path they are served from.
//
// The local-disk driver writes to config.uploadDir, served by app.js at
// /uploads. To use object storage (S3, R2, GCS), replace saveImage with an
// upload to the bucket and return its public or signed URL; job photos accept
// any https URL.
const crypto = require('crypto');
const fs = require('fs/promises');
const path = require('path');
const config = require('../config');
const { HttpError } = require('../middleware/errors');
const { detectImageType } = require('../domain/media');
const { MAX_UPLOAD_BYTES } = require('../domain/constants');

async function saveImage(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length === 0) {
    throw new HttpError(400, 'Send the image file as the request body', 'EMPTY_UPLOAD');
  }
  if (buffer.length > MAX_UPLOAD_BYTES) {
    throw new HttpError(413, `Images must be ${MAX_UPLOAD_BYTES / 1024 / 1024} MB or smaller`, 'TOO_LARGE');
  }
  const type = detectImageType(buffer);
  if (!type) throw new HttpError(415, 'Only JPEG, PNG and WebP images are accepted', 'UNSUPPORTED_IMAGE');

  // 128 random bits: the name is the only access control on a photo.
  const name = `${crypto.randomBytes(16).toString('hex')}.${type.ext}`;
  await fs.mkdir(config.uploadDir, { recursive: true });
  await fs.writeFile(path.join(config.uploadDir, name), buffer, { flag: 'wx' });
  return { url: `/uploads/${name}`, mime: type.mime, bytes: buffer.length };
}

module.exports = { saveImage };
