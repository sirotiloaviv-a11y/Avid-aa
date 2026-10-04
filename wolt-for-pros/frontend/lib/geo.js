// Mirrors backend/src/domain/geo.js.
const EARTH_RADIUS_KM = 6371;
export const AVERAGE_SPEED_KMH = 30;
export const DEFAULT_CENTER = { lat: 32.0853, lng: 34.7818 }; // Tel Aviv

const toRad = (deg) => (deg * Math.PI) / 180;

export function haversineKm(a, b) {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

export function etaSeconds(distanceKm) {
  return Math.max(0, Math.round((distanceKm / AVERAGE_SPEED_KMH) * 3600));
}

export function formatDistance(km) {
  if (km === null || km === undefined) return '—';
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

// One-shot browser position with a timeout; resolves null if unavailable.
export function getBrowserPosition(timeoutMs = 8000) {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 30000 },
    );
  });
}
