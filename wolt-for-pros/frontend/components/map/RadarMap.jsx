'use client';

import { useEffect } from 'react';
import { Circle, MapContainer, Marker, Polyline, Tooltip, useMap } from 'react-leaflet';
import { BaseTiles, pinIcon, SERVICE_GLYPH } from './leafletBase';

function Recenter({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView([center.lat, center.lng], map.getZoom());
  }, [map, center]);
  return null;
}

export default function RadarMap({ me, jobs = [], selectedId, onSelect, radiusKm, target, className = 'h-72' }) {
  return (
    <MapContainer center={[me.lat, me.lng]} zoom={13} className={`${className} w-full rounded-2xl`}>
      <BaseTiles />
      <Recenter center={me} />
      {radiusKm ? (
        <Circle center={[me.lat, me.lng]} radius={radiusKm * 1000} pathOptions={{ color: '#1372f5', weight: 1, fillOpacity: 0.04 }} />
      ) : null}
      <Marker position={[me.lat, me.lng]} icon={pinIcon('me', '📍', { pulse: true })}>
        <Tooltip direction="top" offset={[0, -18]}>You</Tooltip>
      </Marker>
      {target && (
        <>
          <Polyline positions={[[me.lat, me.lng], [target.lat, target.lng]]} pathOptions={{ color: '#1372f5', weight: 4, dashArray: '6 8' }} />
          <Marker position={[target.lat, target.lng]} icon={pinIcon('home', '🏠')}>
            <Tooltip direction="top" offset={[0, -18]}>Client</Tooltip>
          </Marker>
        </>
      )}
      {jobs.map((job) => (
        <Marker
          key={job.id}
          position={[job.latitude, job.longitude]}
          icon={pinIcon(job.canAfford === false ? 'job-locked' : 'job', SERVICE_GLYPH[job.serviceType] || '🛠', { size: job.id === selectedId ? 44 : 36 })}
          eventHandlers={{ click: () => onSelect && onSelect(job.id) }}
        >
          <Tooltip direction="top" offset={[0, -18]}>
            ₪{job.payoutEstimate} payout · {job.distanceKm != null ? `${job.distanceKm} km` : ''}
          </Tooltip>
        </Marker>
      ))}
    </MapContainer>
  );
}
