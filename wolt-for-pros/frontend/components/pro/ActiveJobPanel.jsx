'use client';

import { CheckCircle2, Hammer, Loader2, Navigation, Phone, Radio, Route, Undo2 } from 'lucide-react';
import StatusBadge from '@/components/ui/StatusBadge';
import { RadarMap } from '@/components/map';
import { formatDistance, haversineKm } from '@/lib/geo';
import { formatILS, SERVICE_LABELS } from '@/lib/format';

export default function ActiveJobPanel({
  job,
  position,
  sharing,
  simulating,
  busyAction,
  onToggleSharing,
  onToggleSimulate,
  onStart,
  onFinish,
  onRelease,
}) {
  const target = { lat: job.latitude, lng: job.longitude };
  const distance = position ? haversineKm(position, target) : null;
  const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${job.latitude},${job.longitude}`;

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current job · {SERVICE_LABELS[job.serviceType]}</p>
            <p className="font-semibold">{job.description}</p>
            {job.address && <p className="text-sm text-slate-500">{job.address}</p>}
          </div>
          <StatusBadge status={job.status} />
        </div>
        <RadarMap me={position} target={target} className="h-72" />
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-sm">
          <Stat label="Distance" value={formatDistance(distance)} />
          <Stat label="Estimate" value={formatILS(job.estimatedPrice)} />
          <Stat label="Fee held" value={formatILS(job.platformFee)} />
        </div>
      </div>

      <div className="card space-y-3 p-4">
        {job.client && (
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-500">Client</p>
              <p className="font-semibold">{job.client.name}</p>
            </div>
            <div className="flex gap-2">
              {job.client.phone && (
                <a className="btn-secondary px-3" href={`tel:${job.client.phone}`} aria-label="Call client"><Phone className="h-4 w-4" /></a>
              )}
              <a className="btn-secondary px-3" href={mapsUrl} target="_blank" rel="noreferrer" aria-label="Navigate"><Navigation className="h-4 w-4" /></a>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onToggleSharing} className={`btn flex-1 ${sharing ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'btn-secondary'}`}>
            <Radio className={`h-4 w-4 ${sharing ? 'animate-pulse' : ''}`} /> {sharing ? 'Sharing live GPS' : 'Share live GPS'}
          </button>
          {job.status === 'assigned' && (
            <button type="button" onClick={onToggleSimulate} className={`btn flex-1 ${simulating ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'btn-secondary'}`}>
              <Route className="h-4 w-4" /> {simulating ? 'Stop driver movement' : 'Simulate driver movement'}
            </button>
          )}
        </div>

        {job.status === 'assigned' && (
          <button type="button" className="btn-primary w-full py-3" onClick={onStart} disabled={busyAction === 'start'}>
            {busyAction === 'start' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Hammer className="h-4 w-4" />} I have arrived, start work
          </button>
        )}
        {['assigned', 'in_progress'].includes(job.status) && (
          <button type="button" className="btn-success w-full py-3" onClick={onFinish}>
            <CheckCircle2 className="h-4 w-4" /> Finish job (enter code)
          </button>
        )}
        {job.status === 'assigned' && (
          <button type="button" className="btn w-full text-slate-500 hover:bg-slate-100" onClick={onRelease} disabled={busyAction === 'release'}>
            <Undo2 className="h-4 w-4" /> Can&apos;t make it: release job (fee refunded)
          </button>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl bg-slate-50 px-2 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-bold">{value}</p>
    </div>
  );
}
