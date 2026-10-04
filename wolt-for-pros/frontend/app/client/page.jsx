'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronRight, Crosshair, Loader2, Send } from 'lucide-react';
import AppShell from '@/components/AppShell';
import RoleGate from '@/components/RoleGate';
import ServicePicker, { SERVICE_ICONS } from '@/components/client/ServicePicker';
import StatusBadge from '@/components/ui/StatusBadge';
import Spinner from '@/components/ui/Spinner';
import { LocationPicker } from '@/components/map';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatILS, SERVICE_LABELS, timeAgo } from '@/lib/format';
import { DEFAULT_CENTER, getBrowserPosition } from '@/lib/geo';
import { useSession } from '@/lib/session';
import { useSocketEvent } from '@/lib/socket';

function ClientHome() {
  const { user } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [catalog, setCatalog] = useState(null);
  const [serviceType, setServiceType] = useState('electrician');
  const [description, setDescription] = useState('');
  const [address, setAddress] = useState('');
  const [location, setLocation] = useState(
    user.latitude != null ? { lat: user.latitude, lng: user.longitude } : DEFAULT_CENTER,
  );
  const [locating, setLocating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [jobs, setJobs] = useState(null);

  const loadJobs = useCallback(() => {
    api('/api/jobs/mine').then((d) => setJobs(d.jobs)).catch((err) => toast(err.message, 'error'));
  }, [toast]);

  useEffect(() => {
    api('/api/catalog').then(setCatalog).catch((err) => toast(err.message, 'error'));
    loadJobs();
  }, [loadJobs, toast]);

  useSocketEvent('job:updated', loadJobs);

  async function locateMe() {
    setLocating(true);
    const pos = await getBrowserPosition();
    setLocating(false);
    if (pos) setLocation(pos);
    else toast('Could not get your location. Tap the map to set it.', 'error');
  }

  async function submit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const { job } = await api('/api/jobs/create', {
        method: 'POST',
        body: { serviceType, description, address: address || undefined, latitude: location.lat, longitude: location.lng },
      });
      router.push(`/client/jobs/${job.id}`);
    } catch (err) {
      toast(err.message, 'error');
      setSubmitting(false);
    }
  }

  const selected = catalog && catalog.services.find((s) => s.type === serviceType);
  const activeJobs = (jobs || []).filter((j) => ['requested', 'assigned', 'in_progress'].includes(j.status));
  const pastJobs = (jobs || []).filter((j) => !['requested', 'assigned', 'in_progress'].includes(j.status));

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <form onSubmit={submit} className="space-y-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Hi {user.name.split(' ')[0]}, what needs fixing?</h1>
          <p className="text-sm text-slate-500">A licensed pro near you gets the request instantly.</p>
        </div>

        {catalog ? <ServicePicker services={catalog.services} value={serviceType} onChange={setServiceType} /> : <Spinner />}

        <div className="card space-y-4 p-4 sm:p-5">
          <div>
            <label className="label" htmlFor="desc">Describe the problem</label>
            <textarea
              id="desc"
              className="input min-h-[96px]"
              placeholder={serviceType === 'plumber' ? 'e.g. The kitchen sink is blocked' : serviceType === 'electrician' ? 'e.g. The breaker trips when the AC is on' : 'e.g. Hang shelves on a concrete wall'}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              minLength={5}
              maxLength={1000}
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="label mb-0">Location</span>
              <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700" onClick={locateMe} disabled={locating}>
                {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />} Use my location
              </button>
            </div>
            <LocationPicker value={location} onChange={setLocation} />
            <p className="mt-1.5 text-xs text-slate-500">Tap the map or drag the pin to your door.</p>
          </div>

          <div>
            <label className="label" htmlFor="address">Address details (optional)</label>
            <input id="address" className="input" placeholder="Street, number, floor, apartment" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={200} />
          </div>
        </div>

        {selected && (
          <div className="card flex items-center justify-between gap-4 p-4 sm:p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimated price</p>
              <p className="text-2xl font-extrabold">
                {formatILS(selected.min)} – {formatILS(selected.max)}
              </p>
              <p className="text-xs text-slate-500">Typical {selected.label.toLowerCase()} call-out. Final price agreed on site.</p>
            </div>
            <button className="btn-primary shrink-0 px-5 py-3" disabled={submitting || !catalog}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Request
            </button>
          </div>
        )}
      </form>

      <aside className="space-y-4">
        <h2 className="text-lg font-bold">Your orders</h2>
        {!jobs && <Spinner />}
        {jobs && jobs.length === 0 && <p className="text-sm text-slate-500">No orders yet.</p>}
        {[...activeJobs, ...pastJobs].map((job) => {
          const Icon = SERVICE_ICONS[job.serviceType];
          return (
            <Link key={job.id} href={`/client/jobs/${job.id}`} className="card flex items-center gap-3 p-3 hover:ring-slate-300">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100">
                {Icon && <Icon className="h-5 w-5 text-slate-700" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold">{SERVICE_LABELS[job.serviceType]}</span>
                  <StatusBadge status={job.status} />
                </div>
                <p className="truncate text-xs text-slate-500">{job.description}</p>
                <p className="text-xs text-slate-400">{timeAgo(job.createdAt)} · {formatILS(job.finalPrice ?? job.estimatedPrice)}</p>
              </div>
              <ChevronRight className="h-4 w-4 text-slate-400" />
            </Link>
          );
        })}
      </aside>
    </div>
  );
}

export default function ClientPage() {
  return (
    <AppShell>
      <RoleGate role="client">
        <ClientHome />
      </RoleGate>
    </AppShell>
  );
}
