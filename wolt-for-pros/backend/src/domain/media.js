// Image type detection by magic bytes: the Content-Type a browser sends is
// never trusted on its own.
const SIGNATURES = [
  { ext: 'jpg', mime: 'image/jpeg', test: (b) => b.length > 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff },
  { ext: 'png', mime: 'image/png', test: (b) => b.length > 8 && b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) },
  { ext: 'webp', mime: 'image/webp', test: (b) => b.length > 12 && b.toString('ascii', 0, 4) === 'RIFF' && b.toString('ascii', 8, 12) === 'WEBP' },
];

function detectImageType(buffer) {
  if (!Buffer.isBuffer(buffer)) return null;
  const match = SIGNATURES.find((s) => s.test(buffer));
  return match ? { ext: match.ext, mime: match.mime } : null;
}

const UPLOAD_PATH = /^\/uploads\/[a-f0-9]{32}\.(jpg|png|webp)$/;

// A job photo is either one of our uploads or an external https image URL.
function isAllowedPhotoUrl(url) {
  if (typeof url !== 'string' || url.length > 500) return false;
  if (UPLOAD_PATH.test(url)) return true;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

module.exports = { detectImageType, isAllowedPhotoUrl, UPLOAD_PATH };
