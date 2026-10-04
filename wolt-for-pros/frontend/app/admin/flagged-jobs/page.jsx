'use client';

import { useCallback, useEffect, useState } from 'react';
import { Ban, CheckCircle2, Coins, Gavel, Loader2, RefreshCw, ShieldAlert, Unlock, Users, XCircle } from 'lucide-react';
import AppShell from '@/components/AppShell';
import RoleGate from '@/components/RoleGate';
import StatusBadge from '@/components/ui/StatusBadge';
import Spinner from '@/components/ui/Spinner';
import Modal from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatDateTime, formatILS, SERVICE_LABELS } from '@/lib/format';
import { useSocketEvent } from '@/lib/socket';
import { RatingBadge } from '@/components/ui/StarRating';

const TABS = [
  { key: 'open', label: 'Open disputes', icon: ShieldAlert },
  { key: 'resolved', label: 'Resolved', icon: Gavel },
  { key: 'pros', label: 'Tradespeople', icon: Users },
];

const RESOLUTION_LABELS = {
  approved: 'Approved: fee on final price',
  charged_estimate: 'Rejected: fee on estimate',
  voided: 'Voided: fee released',
};

const PROFILE_BADGE = {
  active: 'bg-emerald-100 text-emerald-800',
  inactive: 'bg-slate-200 text-slate-700',
  suspended: 'bg-rose-100 text-rose-800',
};

function AdminConsole() {
  const toast = useToast();
  const [tab, setTab] = useState('open');
  const [jobs, setJobs] = useState(null);
  const [pros, setPros] = useState(null);
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState(null);
  const [adjusting, setAdjusting] = useState(null); // tradesperson being adjusted

  const loadJobs = useCallback(async (state) => {
    setJobs(null);
    try {
      const data = await api('/api/admin/flagged-jobs', { query: { state } });
      setJobs(data.jobs);
    } catch (err) {
      toast(err.message, 'error');
      setJobs([]);
    }
  }, [toast]);

  const loadPros = useCallback(async () => {
    try {
      const data = await api('/api/admin/tradespeople');
      setPros(data.tradespeople);
    } catch (err) {
      toast(err.message, 'error');
      setPros([]);
    }
  }, [toast]);

  const reload = useCallback(() => {
    if (tab === 'pros') loadPros();
    else loadJobs(tab);
  }, [tab, loadJobs, loadPros]);

  useEffect(() => {
    reload();
  }, [reload]);

  useSocketEvent('flagged:new', (job) => {
    toast(`New flagged job: ${job.tradesperson ? job.tradesperson.name : 'unknown pro'} closed at ${formatILS(job.finalPrice)}`, 'error');
    if (tab === 'open') loadJobs('open');
  });

  async function resolve(job, action) {
    setBusy(`${job.id}:${action}`);
    try {
      await api('/api/admin/flagged-jobs', { method: 'POST', body: { jobId: job.id, action, note: notes[job.id] || undefined } });
      toast('Dispute resolved', 'success');
      setJobs((list) => list.filter((j) => j.id !== job.id));
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(userId, status) {
    setBusy(`${userId}:${status}`);
    try {
      await api(`/api/admin/tradespeople/${userId}/status`, { method: 'POST', body: { status } });
      toast(status === 'suspended' ? 'Account suspended' : 'Account unblocked', 'success');
      if (tab === 'pros') await loadPros();
      else await loadJobs(tab);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Dispute center</h1>
          <p className="text-sm text-slate-500">Jobs closed below 50% of their estimate are held here. Two in 30 days auto-suspends the pro.</p>
        </div>
        <button type="button" className="btn-secondary" onClick={reload}><RefreshCw className="h-4 w-4" /> Refresh</button>
      </div>

      <div className="flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 text-sm font-semibold">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 ${tab === key ? 'bg-white shadow' : 'text-slate-500'}`}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      {tab !== 'pros' && (
        <>
          {!jobs && <Spinner />}
          {jobs && jobs.length === 0 && (
            <div className="card p-10 text-center text-slate-500">
              <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-500" />
              {tab === 'open' ? 'No open disputes.' : 'Nothing resolved yet.'}
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {(jobs || []).map((job) => {
              const ratio = job.estimatedPrice ? Math.round((job.finalPrice / job.estimatedPrice) * 100) : 0;
              const pro = job.tradesperson || {};
              return (
                <article key={job.id} className="card flex flex-col p-4">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {SERVICE_LABELS[job.serviceType]} · flagged {formatDateTime(job.flaggedAt)}
                      </p>
                      <p className="font-semibold">{job.description}</p>
                      <p className="text-xs text-slate-500">Client: {job.client ? `${job.client.name} (${job.client.phone})` : '—'}</p>
                    </div>
                    <StatusBadge status={job.status} />
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
                    <Figure label="Estimate" value={formatILS(job.estimatedPrice)} />
                    <Figure label="Final" value={formatILS(job.finalPrice)} tone="text-rose-600" />
                    <Figure label="Ratio" value={`${ratio}%`} tone={ratio < 50 ? 'text-rose-600' : ''} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{job.flagReason}</p>

                  <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <p className="font-semibold">{pro.name}</p>
                      {pro.status && <span className={`badge ${PROFILE_BADGE[pro.status]}`}>{pro.status}</span>}
                    </div>
                    <p className="text-xs text-slate-500">
                      License {pro.licenseNumber} · fraud score {pro.fraudScore ?? 0} · {job.tradespersonFlagsInWindow} flag(s) in 30 days
                    </p>
                    {pro.wallet && (
                      <p className="mt-1 text-xs text-slate-500">
                        Wallet {formatILS(pro.wallet.balance)} available · {formatILS(pro.wallet.lockedBalance)} locked · this job holds {formatILS(job.platformFee)}
                      </p>
                    )}
                  </div>

                  {job.status === 'flagged' ? (
                    <div className="mt-3 space-y-2">
                      <input
                        className="input"
                        placeholder="Resolution note (optional)"
                        value={notes[job.id] || ''}
                        onChange={(e) => setNotes((n) => ({ ...n, [job.id]: e.target.value }))}
                      />
                      <div className="grid grid-cols-3 gap-2">
                        <ActionButton busy={busy === `${job.id}:approve`} onClick={() => resolve(job, 'approve')} className="btn-success" icon={CheckCircle2} label="Approve" hint="Fee on final price" />
                        <ActionButton busy={busy === `${job.id}:charge_estimate`} onClick={() => resolve(job, 'charge_estimate')} className="btn-danger" icon={Gavel} label="Reject" hint="Fee on estimate" />
                        <ActionButton busy={busy === `${job.id}:void`} onClick={() => resolve(job, 'void')} className="btn-secondary" icon={XCircle} label="Void" hint="Release fee" />
                      </div>
                      <div className="flex gap-2">
                        {pro.status === 'suspended' ? (
                          <button type="button" className="btn-secondary flex-1" onClick={() => setStatus(pro.id, 'active')} disabled={Boolean(busy)}>
                            <Unlock className="h-4 w-4" /> Unblock account
                          </button>
                        ) : (
                          <button type="button" className="btn-secondary flex-1 text-rose-600" onClick={() => setStatus(pro.id, 'suspended')} disabled={Boolean(busy)}>
                            <Ban className="h-4 w-4" /> Suspend
                          </button>
                        )}
                        <button type="button" className="btn-secondary flex-1" onClick={() => setAdjusting({ id: pro.id, name: pro.name })}>
                          <Coins className="h-4 w-4" /> Adjust balance
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-3 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                      {RESOLUTION_LABELS[job.resolution] || job.resolution}
                      {job.resolutionNote ? ` · ${job.resolutionNote}` : ''}
                      {job.resolvedAt ? ` · ${formatDateTime(job.resolvedAt)}` : ''}
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </>
      )}

      {tab === 'pros' && (
        <>
          {!pros && <Spinner />}
          {pros && (
            <div className="card overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Tradesperson</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Rating</th>
                    <th className="px-4 py-3">Flags (30d)</th>
                    <th className="px-4 py-3">Available</th>
                    <th className="px-4 py-3">Locked</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {pros.map((p) => (
                    <tr key={p.id}>
                      <td className="px-4 py-3">
                        <p className="font-semibold">{p.name}</p>
                        <p className="text-xs text-slate-500">{SERVICE_LABELS[p.profile?.serviceType]} · {p.phone} · score {p.profile?.fraudScore ?? 0}</p>
                      </td>
                      <td className="px-4 py-3"><span className={`badge ${PROFILE_BADGE[p.profile?.status] || ''}`}>{p.profile?.status}</span></td>
                      <td className="px-4 py-3"><RatingBadge rating={p.profile?.rating} count={p.profile?.ratingCount} /></td>
                      <td className="px-4 py-3">{p.flagsInWindow}</td>
                      <td className={`px-4 py-3 tabular-nums ${p.wallet && p.wallet.balance < 0 ? 'text-rose-600' : ''}`}>{formatILS(p.wallet?.balance ?? 0)}</td>
                      <td className="px-4 py-3 tabular-nums">{formatILS(p.wallet?.lockedBalance ?? 0)}</td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          {p.profile?.status === 'suspended' ? (
                            <button type="button" className="btn-secondary px-3 py-1.5" onClick={() => setStatus(p.id, 'active')} disabled={Boolean(busy)}>
                              <Unlock className="h-4 w-4" /> Unblock
                            </button>
                          ) : (
                            <button type="button" className="btn-secondary px-3 py-1.5 text-rose-600" onClick={() => setStatus(p.id, 'suspended')} disabled={Boolean(busy)}>
                              <Ban className="h-4 w-4" /> Suspend
                            </button>
                          )}
                          <button type="button" className="btn-secondary px-3 py-1.5" onClick={() => setAdjusting({ id: p.id, name: p.name })}>
                            <Coins className="h-4 w-4" /> Adjust
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <AdjustBalanceModal
        target={adjusting}
        onClose={() => setAdjusting(null)}
        onDone={() => {
          setAdjusting(null);
          reload();
        }}
      />
    </div>
  );
}

function AdjustBalanceModal({ target, onClose, onDone }) {
  const toast = useToast();
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setAmount('');
    setNote('');
  }, [target]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const data = await api(`/api/admin/wallets/${target.id}/adjust`, { method: 'POST', body: { amount: Number(amount), note: note || undefined } });
      toast(`Balance updated: ${formatILS(data.wallet.balance)} available`, 'success');
      onDone();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={Boolean(target)} onClose={onClose} title={target ? `Adjust ${target.name}'s wallet` : 'Adjust wallet'}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="label" htmlFor="adj-amount">Amount (₪). Use a negative number to debit.</label>
          <input id="adj-amount" className="input" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
        </div>
        <div>
          <label className="label" htmlFor="adj-note">Reason</label>
          <input id="adj-note" className="input" placeholder="e.g. Goodwill credit after dispute" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <button className="btn-primary w-full" disabled={busy || !amount || Number(amount) === 0}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} Apply adjustment
        </button>
      </form>
    </Modal>
  );
}

function Figure({ label, value, tone = '' }) {
  return (
    <div className="rounded-xl bg-slate-50 px-2 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function ActionButton({ busy, onClick, className, icon: Icon, label, hint }) {
  return (
    <button type="button" className={`${className} flex-col gap-0.5 px-2 py-2`} onClick={onClick} disabled={busy}>
      <span className="flex items-center gap-1">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}{label}</span>
      <span className="text-[10px] font-normal opacity-80">{hint}</span>
    </button>
  );
}

export default function FlaggedJobsPage() {
  return (
    <AppShell>
      <RoleGate role="admin">
        <AdminConsole />
      </RoleGate>
    </AppShell>
  );
}
