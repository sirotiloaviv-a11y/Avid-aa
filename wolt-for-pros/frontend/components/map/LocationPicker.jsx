'use client';

import { useEffect } from 'react';
import { MapContainer, Marker, useMap, useMapEvents } from 'react-leaflet';
import { BaseTiles, pinIcon } from './leafletBase';

function ClickToSet({ onChange }) {
  useMapEvents({
    click(e) {
      onChange({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  return null;
}

function FollowValue({ value }) {
  const map = useMap();
  useEffect(() => {
    if (value) map.panTo([value.lat, value.lng]);
  }, [map, value]);
  return null;
}

export default function LocationPicker({ value, onChange, className = 'h-64' }) {
  return (
    <MapContainer center={[value.lat, value.lng]} zoom={15} scrollWheelZoom={false} className={`${className} w-full rounded-2xl`}>
      <BaseTiles />
      <ClickToSet onChange={onChange} />
      <FollowValue value={value} />
      <Marker
        position={[value.lat, value.lng]}
        icon={pinIcon('home', '🏠')}
        draggable
        eventHandlers={{
          dragend: (e) => {
            const { lat, lng } = e.target.getLatLng();
            onChange({ lat, lng });
          },
        }}
      />
    </MapContainer>
  );
}
