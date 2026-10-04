'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, BadgeCheck, Clock, FlaskConical, Loader2, Navigation, Phone, Route, ShieldAlert, XCircle } from 'lucide-react';
import AppShell from '@/components/AppShell';
import RoleGate from '@/components/RoleGate';
import CompletionCode from '@/components/client/CompletionCode';
import StatusSteps from '@/components/client/StatusSteps';
import StatusBadge from '@/components/ui/StatusBadge';
import Spinner from '@/components/ui/Spinner';
import { TrackingMap } from '@/components/map';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatDateTime, formatILS, SERVICE_LABELS } from '@/lib/format';
import { etaSeconds, formatDistance, haversineKm } from '@/lib/geo';
import { useJobChannel, useSocketEvent } from '@/lib/socket';
import { useSession } from '@/lib/session';
import { isDemoDriving, toggleDemoDrive } from '@/lib/demo/mockServer';

const LIVE_STATUSES = ['assigned', 'in_progress'];

// Counts down between GPS updates so the ETA feels live rather than jumping.
function useCountdown(targetMs) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!targetMs) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [targetMs]);
  return targetMs ? Math.max(0, Math.round((targetMs - now) / 1000)) : null;
}

function formatCountdown(seconds) {
  if (seconds === null) return '—';
  if (seconds < 60) return seconds === 0 ? 'Arriving' : `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')} min`;
}

function JobTracking({ jobId }) {
  const toast = useToast();
  const { mode } = useSession();
  const demo = mode === 'demo';
  const [driving, setDriving] = useState(() => demo && isDemoDriving(jobId));
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [pro, setPro] = useState(null); // { lat, lng, distanceKm, at }
  const [etaTarget, setEtaTarget] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/jobs/${jobId}`);
      setJob(data.job);
      return data.job;
    } catch (err) {
      setError(err.message);
      return null;
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  const applyLocation = useCallback((loc) => {
    if (!loc) return;
    setPro({ lat: loc.lat, lng: loc.lng, distanceKm: loc.distanceKm, at: loc.at });
    setEtaTarget(Date.now() + etaSeconds(loc.distanceKm) * 1000);
  }, []);

  useJobChannel(jobId, (ack) => applyLocation(ack.location));

  useSocketEvent('pro:location', (loc) => {
    if (loc.jobId === jobId) applyLocation(loc);
  });

  useSocketEvent('job:updated', (payload) => {
    if (payload.id !== jobId) return;
    load().then((fresh) => {
      if (!fresh) return;
      if (fresh.status === 'assigned' && job && job.status === 'requested') toast(`${fresh.tradesperson?.name || 'A pro'} accepted your job`, 'success');
      if (fresh.status === 'requested' && job && job.status === 'assigned') toast('Your pro had to drop the job. Finding you another one.', 'info');
      if (fresh.status === 'completed') toast('Job completed. Thanks for using Wolt for Pros!', 'success');
    });
  });

  // Fall back to the pro's last stored position until live GPS arrives.
  useEffect(() => {
    if (!pro && job && job.tradesperson && job.tradesperson.latitude != null && LIVE_STATUSES.includes(job.status)) {
      const p = { lat: job.tradesperson.latitude, lng: job.tradesperson.longitude };
      applyLocation({ ...p, distanceKm: haversineKm(p, { lat: job.latitude, lng: job.longitude }) });
    }
  }, [job, pro, applyLocation]);

  useSocketEvent('demo:drive', (msg) => {
    if (msg.jobId !== jobId) return;
    setDriving(msg.active);
    if (msg.arrived) toast('Your pro has arrived!', 'success');
  });

  const countdown = useCountdown(job && job.status === 'assigned' ? etaTarget : null);

  async function cancel() {
    if (!window.confirm('Cancel this request?')) return;
    setCancelling(true);
    try {
      const data = await api(`/api/jobs/${jobId}/cancel`, { method: 'POST', body: {} });
      setJob(data.job);
      toast('Request cancelled', 'info');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setCancelling(false);
    }
  }

  if (error) return <p className="py-10 text-center text-rose-600">{error}</p>;
  if (!job) return <Spinner />;

  const home = { lat: job.latitude, lng: job.longitude };
  const live = LIVE_STATUSES.includes(job.status);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href="/client" className="rounded-full p-2 hover:bg-slate-100" aria-label="Back">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-extrabold">{SERVICE_LABELS[job.serviceType]}</h1>
          <p className="truncate text-sm text-slate-500">{job.address || job.description}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="card p-4">
        <StatusSteps status={job.status} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <div className="relative">
            <TrackingMap home={home} pro={live ? pro : null} serviceType={job.serviceType} className="h-80 sm:h-[420px]" />
            {job.status === 'assigned' && (
              <div className="absolute left-3 top-3 z-[400] rounded-2xl bg-white/95 px-4 py-3 shadow-card">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Clock className="h-3.5 w-3.5" /> ETA
                </p>
                <p className="text-2xl font-extrabold tabular-nums">{pro ? formatCountdown(countdown) : '…'}</p>
                {pro && <p className="text-xs text-slate-500">{formatDistance(pro.distanceKm)} away</p>}
              </div>
            )}
          </div>

          {demo && job.status === 'assigned' && (
            <div className="card flex items-center justify-between gap-3 border border-dashed border-amber-300 bg-amber-50/60 p-4">
              <p className="flex items-center gap-2 text-sm text-amber-900">
                <FlaskConical className="h-4 w-4 shrink-0" /> Demo: watch your pro drive over in real time.
              </p>
              <button type="button" onClick={() => toggleDemoDrive(job.id)} className={`btn shrink-0 ${driving ? 'bg-amber-200 text-amber-900' : 'btn-primary'}`}>
                <Route className="h-4 w-4" /> {driving ? 'Stop' : 'Simulate Driver Movement'}
              </button>
            </div>
          )}

          {job.status === 'requested' && (
            <div className="card flex items-center gap-3 p-4">
              <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
              <div>
                <p className="font-semibold">Finding a {SERVICE_LABELS[job.serviceType].toLowerCase()} near you…</p>
                <p className="text-sm text-slate-500">Nearby pros can see your request now.</p>
              </div>
            </div>
          )}

          {job.tradesperson && live && (
            <div className="card flex items-center gap-3 p-4">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-100 text-lg font-bold text-brand-700">
                {job.tradesperson.name.charAt(0)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1 font-semibold">
                  {job.tradesperson.name} <BadgeCheck className="h-4 w-4 text-brand-600" />
                </p>
                <p className="text-xs text-slate-500">License {job.tradesperson.licenseNumber}</p>
                <p className="text-xs text-slate-500">
                  {job.status === 'in_progress' ? 'Working on your job' : (
                    <span className="inline-flex items-center gap-1"><Navigation className="h-3 w-3" /> On the way</span>
                  )}
                </p>
              </div>
              {job.tradesperson.phone && (
                <a href={`tel:${job.tradesperson.phone}`} className="btn-secondary px-3" aria-label="Call">
                  <Phone className="h-4 w-4" />
                </a>
              )}
            </div>
          )}
        </div>

        <div className="space-y-4">
          {live && job.completionCode && <CompletionCode code={job.completionCode} />}

          {job.status === 'flagged' && (
            <div className="card flex gap-3 border-l-4 border-rose-500 p-4">
              <ShieldAlert className="h-5 w-5 shrink-0 text-rose-600" />
              <div>
                <p className="font-semibold">Under review</p>
                <p className="text-sm text-slate-600">The final price was well below the estimate, so our team is checking this job. Nothing is needed from you.</p>
              </div>
            </div>
          )}

          <div className="card space-y-2 p-4 text-sm">
            <Row label="Estimated price" value={formatILS(job.estimatedPrice)} />
            {job.finalPrice != null && <Row label="Final price" value={formatILS(job.finalPrice)} strong />}
            <Row label="Requested" value={formatDateTime(job.createdAt)} />
            {job.completedAt && <Row label="Completed" value={formatDateTime(job.completedAt)} />}
            <p className="border-t border-slate-100 pt-2 text-slate-600">{job.description}</p>
          </div>

          {['requested', 'assigned'].includes(job.status) && (
            <button type="button" className="btn-secondary w-full text-rose-600" onClick={cancel} disabled={cancelling}>
              {cancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />} Cancel request
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, strong }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-slate-500">{label}</span>
      <span className={strong ? 'font-bold' : 'font-medium'}>{value}</span>
    </div>
  );
}

export default function JobPage({ params }) {
  return (
    <AppShell>
      <RoleGate role="client">
        <JobTracking jobId={params.id} />
      </RoleGate>
    </AppShell>
  );
}
