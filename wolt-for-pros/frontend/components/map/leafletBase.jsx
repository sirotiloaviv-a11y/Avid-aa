'use client';

// Client-only: imports Leaflet, which touches `window` at import time. Only
// load this through the dynamic wrappers in ./index.jsx.
import L from 'leaflet';
import { TileLayer } from 'react-leaflet';

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

export function BaseTiles() {
  if (MAPBOX_TOKEN) {
    return (
      <TileLayer
        url={`https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/{z}/{x}/{y}?access_token=${MAPBOX_TOKEN}`}
        tileSize={512}
        zoomOffset={-1}
        attribution='&copy; <a href="https://www.mapbox.com/about/maps/">Mapbox</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      />
    );
  }
  return (
    <TileLayer
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    />
  );
}

// Custom HTML markers avoid Leaflet's default PNG icons, whose URLs break
// under bundlers.
const iconCache = new Map();
export function pinIcon(variant, glyph, { pulse = false, size = 36 } = {}) {
  const key = `${variant}|${glyph}|${pulse}|${size}`;
  if (!iconCache.has(key)) {
    iconCache.set(key, L.divIcon({
      className: '',
      html: `<div class="map-pin map-pin--${variant}${pulse ? ' map-pin--pulse' : ''}" style="width:${size}px;height:${size}px">${glyph}</div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    }));
  }
  return iconCache.get(key);
}

export const SERVICE_GLYPH = { electrician: '⚡', plumber: '💧', handyman: '🔨' };
