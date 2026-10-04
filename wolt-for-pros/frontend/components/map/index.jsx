'use client';

import dynamic from 'next/dynamic';

function MapSkeleton({ className = 'h-72' }) {
  return <div className={`${className} w-full animate-pulse rounded-2xl bg-slate-200`} />;
}

// Leaflet needs `window`, so the maps render on the client only.
export const LocationPicker = dynamic(() => import('./LocationPicker'), { ssr: false, loading: () => <MapSkeleton className="h-64" /> });
export const TrackingMap = dynamic(() => import('./TrackingMap'), { ssr: false, loading: () => <MapSkeleton /> });
export const RadarMap = dynamic(() => import('./RadarMap'), { ssr: false, loading: () => <MapSkeleton /> });
