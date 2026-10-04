'use client';

import { CheckCircle2, Clock, Loader2, Lock, MapPin } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import PhotoGallery from '@/components/PhotoGallery';
import { formatDistance } from '@/lib/geo';
import { formatILS, SERVICE_LABELS } from '@/lib/format';

// Shown before a pro commits: the client's description and photos, the
// money, and the Accept button (which holds the fee).
export default function JobDetailsModal({ job, available, disabledReason = null, accepting = false, onClose, onAccept, onTopUp }) {
  if (!job) return null;
  const canAfford = available >= job.feeAmount;
  const blocked = Boolean(disabledReason) || !canAfford;
  return (
    <Modal open={Boolean(job)} onClose={onClose} title={`${SERVICE_LABELS[job.serviceType]} job`}>
      <div className="space-y-4">
        <div>
          <p className="font-semibold">{job.description}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" /> {formatDistance(job.distanceKm)}{job.address ? ` · ${job.address}` : ''}</span>
            {job.etaMinutes != null && <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> ~{job.etaMinutes} min drive</span>}
          </p>
          {job.client && <p className="mt-1 text-xs text-slate-500">Client: {job.client.name}</p>}
        </div>

        <div>
          <p className="label">Photos from the client</p>
          <PhotoGallery photos={job.photos || []} size="h-24 w-24" emptyLabel="No photos attached" />
        </div>

        <div className="grid grid-cols-3 gap-2 text-center text-sm">
          <div className="rounded-xl bg-slate-50 p-2"><p className="text-[11px] uppercase tracking-wide text-slate-500">Estimate</p><p className="font-bold">{formatILS(job.estimatedPrice)}</p></div>
          <div className="rounded-xl bg-slate-50 p-2"><p className="text-[11px] uppercase tracking-wide text-slate-500">Fee held</p><p className="font-bold">{formatILS(job.feeAmount)}</p></div>
          <div className="rounded-xl bg-emerald-50 p-2"><p className="text-[11px] uppercase tracking-wide text-emerald-700">Est. payout</p><p className="font-bold text-emerald-700">{formatILS(job.payoutEstimate)}</p></div>
        </div>

        {!canAfford && (
          <p className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
            You need {formatILS(job.feeAmount)} available to cover the fee.{' '}
            <button type="button" className="font-semibold underline" onClick={onTopUp}>Top up</button>
          </p>
        )}
        {disabledReason && canAfford && <p className="text-sm text-slate-500">{disabledReason}</p>}

        <button type="button" className="btn-primary w-full py-3" disabled={blocked || accepting} onClick={onAccept}>
          {accepting ? <Loader2 className="h-4 w-4 animate-spin" /> : blocked ? <Lock className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
          Accept job · {formatILS(job.feeAmount)} fee held
        </button>
      </div>
    </Modal>
  );
}
