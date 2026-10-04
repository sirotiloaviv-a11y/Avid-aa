'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertOctagon, History, Power, Radar } from 'lucide-react';
import AppShell from '@/components/AppShell';
import RoleGate from '@/components/RoleGate';
import WalletCard from '@/components/pro/WalletCard';
import TopUpModal from '@/components/pro/TopUpModal';
import JobCard from '@/components/pro/JobCard';
import ExecutionModal from '@/components/pro/ExecutionModal';
import ActiveJobPanel from '@/components/pro/ActiveJobPanel';
import Spinner from '@/components/ui/Spinner';
import { RadarMap } from '@/components/map';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatDateTime, formatILS, SERVICE_LABELS } from '@/lib/format';
import { DEFAULT_CENTER, getBrowserPosition } from '@/lib/geo';
import { useSession } from '@/lib/session';
import { getSocket, useSocketEvent } from '@/lib/socket';

const RADAR_RADIUS_KM = 25;
const SIM_STEP_MS = 1500;
const SIM_STEPS = 40;

const TX_LABELS = {
  deposit: 'Top-up',
  fee_hold: 'Fee held',
  fee_deduction: 'Fee charged',
  refund: 'Fee released',
  adjustment: 'Adjustment',
};

function emitLocation(pos) {
  const s = getSocket();
  if (s && pos) s.emit('location:update', { lat: pos.lat, lng: pos.lng });
}

function ProDashboard() {
  const { user } = useSession();
  const toast = useToast();
  const [me, setMe] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [position, setPosition] = useState(
    user.latitude != null ? { lat: user.latitude, lng: user.longitude } : DEFAULT_CENTER,
  );
  const [jobs, setJobs] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [acceptingId, setAcceptingId] = useState(null);
  const [topUp, setTopUp] = useState({ open: false, suggested: null });
  const [executing, setExecuting] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [busyAction, setBusyAction] = useState(null);

  const positionRef = useRef(position);
  positionRef.current = position;

  const loadMe = useCallback(async () => {
    try {
      setMe(await api('/api/pros/me'));
    } catch (err) {
      toast(err.message, 'error');
    }
  }, [toast]);

  const loadWallet = useCallback(async () => {
    try {
      const data = await api('/api/wallet/balance');
      setMe((m) => (m ? { ...m, wallet: data.wallet } : m));
      setTransactions(data.transactions);
    } catch (err) {
      toast(err.message, 'error');
    }
  }, [toast]);

  const loadNearby = useCallback(async () => {
    const p = positionRef.current;
    try {
      const data = await api('/api/jobs/nearby', { query: { lat: p.lat, lng: p.lng, radiusKm: RADAR_RADIUS_KM } });
      setJobs(data.jobs);
    } catch (err) {
      toast(err.message, 'error');
    }
  }, [toast]);

  // Initial load, browser position, and Stripe redirect handling.
  useEffect(() => {
    loadMe();
    loadWallet();
    api('/api/catalog').then(setCatalog).catch(() => {});
    getBrowserPosition().then((pos) => {
      if (pos) {
        setPosition(pos);
        emitLocation(pos);
      }
    });

    const params = new URLSearchParams(window.location.search);
    const topup = params.get('topup');
    const sessionId = params.get('session_id');
    if (topup) window.history.replaceState(null, '', '/pro');
    if (topup === 'cancelled') toast('Top-up cancelled', 'info');
    if (topup === 'success' && sessionId) {
      api(`/api/wallet/checkout-session/${encodeURIComponent(sessionId)}`)
        .then((res) => {
          if (res.status === 'paid') toast('Payment received. Your wallet has been topped up.', 'success');
          else toast('Payment is processing. Your balance will update shortly.', 'info');
          loadWallet();
        })
        .catch((err) => toast(err.message, 'error'));
    }
  }, [loadMe, loadWallet, toast]);

  const profile = me && me.profile;
  const wallet = me && me.wallet;
  const activeJob = me && me.activeJob;
  const online = profile && profile.status === 'active';
  const suspended = profile && profile.status === 'suspended';
  const feeRate = (catalog && catalog.feeRate) || 0.15;
  // Effects below key on the job id so a refetched (but unchanged) job does
  // not restart GPS watching or the drive simulation.
  const activeJobId = activeJob ? activeJob.id : null;
  const activeJobRef = useRef(activeJob);
  activeJobRef.current = activeJob;

  // Refresh the radar when going online or when the position moves ~0.5 km.
  const coarseKey = `${position.lat.toFixed(2)},${position.lng.toFixed(2)}`;
  useEffect(() => {
    if (online && !activeJobId) loadNearby();
  }, [online, activeJobId, coarseKey, loadNearby]);

  useSocketEvent('job:new', () => online && !activeJob && loadNearby());
  useSocketEvent('job:taken', ({ id }) => setJobs((list) => (list ? list.filter((j) => j.id !== id) : list)));
  useSocketEvent('wallet:updated', () => loadWallet());
  useSocketEvent('profile:updated', ({ status }) => {
    setMe((m) => (m ? { ...m, profile: { ...m.profile, status } } : m));
    if (status === 'suspended') toast('Your account has been suspended pending review.', 'error');
    if (status === 'active') toast('Your account is active again.', 'success');
  });
  useSocketEvent('job:updated', (job) => {
    if (activeJob && job.id === activeJob.id) {
      if (job.status === 'cancelled') toast('The client cancelled the job. Your fee was released.', 'info');
      loadMe();
    }
  });

  // Live GPS from the device while a job is active and sharing is on.
  useEffect(() => {
    if (!activeJobId || !sharing || simulating || !navigator.geolocation) return undefined;
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setPosition(p);
        emitLocation(p);
      },
      () => {
        toast('Location permission denied. Use "Simulate drive" to demo tracking.', 'error');
        setSharing(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [activeJobId, sharing, simulating, toast]);

  // Demo mode: drive in a straight line to the client.
  useEffect(() => {
    const job = activeJobRef.current;
    if (!activeJobId || !job || !simulating) return undefined;
    const start = positionRef.current;
    const end = { lat: job.latitude, lng: job.longitude };
    let step = 0;
    emitLocation(start);
    const timer = setInterval(() => {
      step += 1;
      const t = Math.min(1, step / SIM_STEPS);
      const p = { lat: start.lat + (end.lat - start.lat) * t, lng: start.lng + (end.lng - start.lng) * t };
      setPosition(p);
      emitLocation(p);
      if (t >= 1) {
        clearInterval(timer);
        setSimulating(false);
        toast('You have arrived at the client.', 'success');
      }
    }, SIM_STEP_MS);
    return () => clearInterval(timer);
  }, [activeJobId, simulating, toast]);

  async function setOnline(next) {
    try {
      const data = await api('/api/pros/me/availability', { method: 'POST', body: { online: next } });
      setMe((m) => ({ ...m, profile: data.profile }));
      if (next) emitLocation(positionRef.current);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function accept(job) {
    setAcceptingId(job.id);
    try {
      const p = positionRef.current;
      await api(`/api/jobs/${job.id}/accept`, { method: 'POST', body: { latitude: p.lat, longitude: p.lng } });
      toast(`Job accepted. ${formatILS(job.feeAmount)} fee held from your wallet.`, 'success');
      setSharing(true);
      await Promise.all([loadMe(), loadWallet()]);
      emitLocation(p);
    } catch (err) {
      if (err.code === 'INSUFFICIENT_BALANCE') {
        setTopUp({ open: true, suggested: Math.max(0, job.feeAmount - (wallet ? wallet.balance : 0)) });
      }
      toast(err.message, 'error');
      if (err.code === 'JOB_NOT_AVAILABLE') loadNearby();
    } finally {
      setAcceptingId(null);
    }
  }

  async function startJob() {
    setBusyAction('start');
    try {
      await api(`/api/jobs/${activeJob.id}/start`, { method: 'POST', body: {} });
      setSimulating(false);
      await loadMe();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusyAction(null);
    }
  }

  async function releaseJob() {
    if (!window.confirm('Release this job? It goes back to other pros and your held fee is refunded.')) return;
    setBusyAction('release');
    try {
      await api(`/api/jobs/${activeJob.id}/cancel`, { method: 'POST', body: { reason: 'Released by tradesperson' } });
      setSimulating(false);
      setSharing(false);
      toast('Job released. Fee refunded to your wallet.', 'info');
      await Promise.all([loadMe(), loadWallet()]);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusyAction(null);
    }
  }

  async function complete({ completionCode, finalPrice }) {
    const res = await api(`/api/jobs/${activeJob.id}/verify-and-complete`, {
      method: 'POST',
      body: { completionCode, finalPrice },
    });
    setExecuting(false);
    setSharing(false);
    setSimulating(false);
    if (res.outcome === 'flagged') {
      toast(
        res.suspended
          ? 'Job sent for review. Your account is suspended until our team checks your recent jobs.'
          : 'Job sent for review because the price is far below the estimate. Your fee stays held until it is resolved.',
        'error',
        8000,
      );
    } else {
      toast(`Job complete. ${formatILS(res.job.platformFee)} fee charged.`, 'success');
    }
    await Promise.all([loadMe(), loadWallet()]);
  }

  const disabledReason = suspended
    ? 'Your account is suspended'
    : !online
      ? 'Go online to accept jobs'
      : activeJob
        ? 'Finish your current job first'
        : null;

  const sortedJobs = useMemo(() => jobs || [], [jobs]);
  const presets = (catalog && catalog.topUp && catalog.topUp.presets) || undefined;

  if (!me) return <Spinner />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">{user.name}</h1>
          <p className="text-sm text-slate-500">
            {SERVICE_LABELS[profile.serviceType]} · License {profile.licenseNumber}
          </p>
        </div>
        {!suspended && (
          <button
            type="button"
            onClick={() => setOnline(!online)}
            className={`btn rounded-full px-5 ${online ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300'}`}
          >
            <Power className="h-4 w-4" /> {online ? 'Online' : 'Offline'}
          </button>
        )}
      </div>

      {suspended && (
        <div className="card flex gap-3 border-l-4 border-rose-500 p-4">
          <AlertOctagon className="h-5 w-5 shrink-0 text-rose-600" />
          <div>
            <p className="font-semibold">Account suspended</p>
            <p className="text-sm text-slate-600">
              Several of your recent jobs closed far below their estimate. Our team is reviewing them; you can&apos;t accept new jobs until then.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        <div className="order-2 space-y-4 lg:order-1">
          {activeJob ? (
            <ActiveJobPanel
              job={activeJob}
              position={position}
              sharing={sharing}
              simulating={simulating}
              busyAction={busyAction}
              onToggleSharing={() => setSharing((s) => !s)}
              onToggleSimulate={() => setSimulating((s) => !s)}
              onStart={startJob}
              onFinish={() => setExecuting(true)}
              onRelease={releaseJob}
            />
          ) : (
            <>
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-lg font-bold">
                  <Radar className="h-5 w-5 text-brand-600" /> Live job radar
                </h2>
                <span className="text-xs text-slate-500">{online ? `Within ${RADAR_RADIUS_KM} km` : 'Offline'}</span>
              </div>
              <RadarMap me={position} jobs={online ? sortedJobs : []} selectedId={selectedId} onSelect={setSelectedId} radiusKm={RADAR_RADIUS_KM} />
              {!online && !suspended && (
                <div className="card p-6 text-center">
                  <p className="mb-3 text-slate-600">You are offline. Go online to see jobs near you.</p>
                  <button type="button" className="btn-success" onClick={() => setOnline(true)}><Power className="h-4 w-4" /> Go online</button>
                </div>
              )}
              {online && !jobs && <Spinner label="Scanning for jobs…" />}
              {online && jobs && jobs.length === 0 && (
                <p className="card p-6 text-center text-sm text-slate-500">No open {SERVICE_LABELS[profile.serviceType].toLowerCase()} jobs nearby right now. New ones appear here instantly.</p>
              )}
              {online && sortedJobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  selected={job.id === selectedId}
                  available={wallet ? wallet.balance : 0}
                  accepting={acceptingId === job.id}
                  disabledReason={disabledReason}
                  onSelect={() => setSelectedId(job.id)}
                  onAccept={() => accept(job)}
                  onTopUp={() => setTopUp({ open: true, suggested: Math.max(0, job.feeAmount - (wallet ? wallet.balance : 0)) })}
                />
              ))}
            </>
          )}
        </div>

        <aside className="order-1 space-y-4 lg:order-2">
          <WalletCard wallet={wallet} feeRate={feeRate} onTopUp={() => setTopUp({ open: true, suggested: null })} />
          <div className="card p-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-bold"><History className="h-4 w-4" /> Wallet activity</h3>
            {transactions.length === 0 && <p className="text-sm text-slate-500">No activity yet.</p>}
            <ul className="divide-y divide-slate-100">
              {transactions.slice(0, 8).map((tx) => (
                <li key={tx.id} className="flex items-center justify-between py-2 text-sm">
                  <div>
                    <p className="font-medium">{TX_LABELS[tx.type] || tx.type}</p>
                    <p className="text-xs text-slate-400">{formatDateTime(tx.createdAt)}</p>
                  </div>
                  <span className={`font-semibold tabular-nums ${tx.amount >= 0 ? 'text-emerald-600' : 'text-slate-700'}`}>
                    {tx.amount >= 0 ? '+' : ''}{formatILS(tx.amount)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>

      <TopUpModal
        open={topUp.open}
        suggested={topUp.suggested}
        presets={presets}
        onClose={() => setTopUp({ open: false, suggested: null })}
        onCredited={() => loadWallet()}
      />
      <ExecutionModal open={executing} onClose={() => setExecuting(false)} job={activeJob} feeRate={feeRate} onSubmit={complete} />
    </div>
  );
}

export default function ProPage() {
  return (
    <AppShell>
      <RoleGate role="tradesperson">
        <ProDashboard />
      </RoleGate>
    </AppShell>
  );
}
