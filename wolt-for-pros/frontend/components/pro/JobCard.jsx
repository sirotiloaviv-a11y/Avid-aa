import { Lock, MapPin, Clock, Eye, ImageIcon, Loader2 } from 'lucide-react';
import { mediaUrl } from '@/lib/images';
import { formatDistance } from '@/lib/geo';
import { formatILS, timeAgo } from '@/lib/format';

export default function JobCard({ job, selected = false, available = 0, accepting = false, disabledReason = null, onSelect, onAccept, onTopUp }) {
  const canAfford = available >= job.feeAmount;
  const blocked = Boolean(disabledReason);
  return (
    <div
      className={`card cursor-pointer p-4 transition ${selected ? 'ring-2 ring-brand-500' : 'hover:ring-slate-300'}`}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
      role="button"
      tabIndex={0}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="line-clamp-2 font-semibold">{job.description}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" /> {formatDistance(job.distanceKm)}</span>
            {job.etaMinutes != null && <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> ~{job.etaMinutes} min</span>}
            <span>{timeAgo(job.createdAt)}</span>
          </p>
          {job.address && <p className="mt-1 truncate text-xs text-slate-400">{job.address}</p>}
        </div>
        {job.photos && job.photos.length > 0 && (
          <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200">
            <img src={mediaUrl(job.photos[0])} alt="" className="h-full w-full object-cover" loading="lazy" />
            {job.photos.length > 1 && (
              <span className="absolute bottom-0.5 right-0.5 inline-flex items-center gap-0.5 rounded-md bg-slate-900/70 px-1 text-[10px] font-semibold text-white">
                <ImageIcon className="h-2.5 w-2.5" />{job.photos.length}
              </span>
            )}
          </div>
        )}
        <div className="shrink-0 text-right">
          <p className="text-xs text-slate-500">Est. payout</p>
          <p className="text-lg font-extrabold text-emerald-600">{formatILS(job.payoutEstimate)}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2 text-xs">
        <span className="text-slate-500">Job estimate <strong className="text-slate-800">{formatILS(job.estimatedPrice)}</strong></span>
        <span className="text-slate-500">Fee held <strong className="text-slate-800">{formatILS(job.feeAmount)}</strong></span>
      </div>

      <div className="mt-3 flex gap-2" onClick={(e) => e.stopPropagation()} role="presentation">
        <button
          type="button"
          className="btn-primary flex-1"
          disabled={!canAfford || blocked || accepting}
          onClick={onAccept}
          title={disabledReason || (!canAfford ? 'Wallet balance is below the platform fee' : undefined)}
        >
          {accepting ? <Loader2 className="h-4 w-4 animate-spin" /> : canAfford ? <Eye className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
          {canAfford ? 'Review & accept' : 'Balance too low'}
        </button>
        {!canAfford && (
          <button type="button" className="btn-secondary" onClick={onTopUp}>Top up</button>
        )}
      </div>
      {!canAfford && (
        <p className="mt-2 text-xs text-amber-700">
          You need {formatILS(job.feeAmount)} available to cover the fee. Top up to accept.
        </p>
      )}
      {blocked && canAfford && <p className="mt-2 text-xs text-slate-500">{disabledReason}</p>}
    </div>
  );
}
