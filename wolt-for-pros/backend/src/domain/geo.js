const EARTH_RADIUS_KM = 6371;
// Average urban driving speed used for ETAs.
const AVERAGE_SPEED_KMH = 30;

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function haversineKm(a, b) {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

function etaMinutes(distanceKm, speedKmh = AVERAGE_SPEED_KMH) {
  return Math.max(0, Math.ceil((distanceKm / speedKmh) * 60));
}

function isValidCoordinate(lat, lng) {
  return (
    typeof lat === 'number' && typeof lng === 'number' &&
    Number.isFinite(lat) && Number.isFinite(lng) &&
    lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180
  );
}

module.exports = { haversineKm, etaMinutes, isValidCoordinate, AVERAGE_SPEED_KMH };
