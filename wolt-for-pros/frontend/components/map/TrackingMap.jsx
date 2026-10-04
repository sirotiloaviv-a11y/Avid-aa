'use client';

import { useEffect, useRef } from 'react';
import { MapContainer, Marker, Polyline, Tooltip, useMap } from 'react-leaflet';
import { BaseTiles, pinIcon, SERVICE_GLYPH } from './leafletBase';

// Fit both points once when the tradesperson first appears; after that keep
// the tradesperson in view without fighting the user's own panning.
function KeepInView({ home, pro }) {
  const map = useMap();
  const fitted = useRef(false);
  useEffect(() => {
    if (!pro) {
      map.setView([home.lat, home.lng], map.getZoom());
      return;
    }
    if (!fitted.current) {
      map.fitBounds([[home.lat, home.lng], [pro.lat, pro.lng]], { padding: [48, 48], maxZoom: 16 });
      fitted.current = true;
    } else if (!map.getBounds().pad(-0.1).contains([pro.lat, pro.lng])) {
      map.panTo([pro.lat, pro.lng]);
    }
  }, [map, home.lat, home.lng, pro]);
  return null;
}

export default function TrackingMap({ home, pro, serviceType, className = 'h-72' }) {
  return (
    <MapContainer center={[home.lat, home.lng]} zoom={15} className={`${className} w-full rounded-2xl`}>
      <BaseTiles />
      <KeepInView home={home} pro={pro} />
      <Marker position={[home.lat, home.lng]} icon={pinIcon('home', '🏠')}>
        <Tooltip direction="top" offset={[0, -18]}>Your location</Tooltip>
      </Marker>
      {pro && (
        <>
          <Polyline positions={[[pro.lat, pro.lng], [home.lat, home.lng]]} pathOptions={{ color: '#1372f5', weight: 4, dashArray: '6 8', opacity: 0.8 }} />
          <Marker position={[pro.lat, pro.lng]} icon={pinIcon('pro', SERVICE_GLYPH[serviceType] || '🛠', { pulse: true })}>
            <Tooltip direction="top" offset={[0, -18]}>Your pro</Tooltip>
          </Marker>
        </>
      )}
    </MapContainer>
  );
}
