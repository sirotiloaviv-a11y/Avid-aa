'use client';

import { API_URL } from './config.js';

// Photos are shrunk in the browser before upload: phone photos are often
// 5-12 MB, and a job photo only needs to show the problem.
const MAX_DIMENSION = 1600;
const JPEG_QUALITY = 0.82;
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('That file is not an image this browser can read'));
    };
    img.src = url;
  });
}

/**
 * @param {File} file
 * @param {{ maxDimension?: number, quality?: number }} [options]
 * @returns {Promise<Blob>} a JPEG
 */
export async function resizeImage(file, { maxDimension = MAX_DIMENSION, quality = JPEG_QUALITY } = {}) {
  const img = await loadImage(file);
  const scale = Math.min(1, maxDimension / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.naturalWidth * scale);
  canvas.height = Math.round(img.naturalHeight * scale);
  const ctx = canvas.getContext('2d');
  // JPEG has no transparency: paint white behind PNGs.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Could not process the image'))), 'image/jpeg', quality);
  });
}

// Uploaded photos come back as "/uploads/..." on the API host.
export function mediaUrl(url) {
  if (typeof url === 'string' && url.startsWith('/uploads/')) return `${API_URL}${url}`;
  return url;
}
