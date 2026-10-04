'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import { formatILS } from '@/lib/format';

export default function ExecutionModal({ open, onClose, job, feeRate, onSubmit }) {
  const [code, setCode] = useState('');
  const [finalPrice, setFinalPrice] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const jobId = job ? job.id : null;
  const estimate = job ? job.estimatedPrice : null;
  useEffect(() => {
    if (open && jobId) {
      setCode('');
      setFinalPrice(String(estimate));
      setError(null);
    }
  }, [open, jobId, estimate]);

  if (!job) return null;
  const price = Number(finalPrice);
  const validPrice = Number.isFinite(price) && price > 0;
  const fee = validPrice ? Math.round(price * feeRate * 100) / 100 : null;
  const underpriced = validPrice && price < job.estimatedPrice * 0.5;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ completionCode: code, finalPrice: price });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Finish job">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="code">Client&apos;s completion code</label>
          <input
            id="code"
            className="input text-center font-mono text-3xl tracking-[0.6em]"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{4}"
            maxLength={4}
            placeholder="••••"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
            required
            autoFocus
          />
          <p className="mt-1 text-xs text-slate-500">Ask the client for the 4-digit code shown in their app.</p>
        </div>
        <div>
          <label className="label" htmlFor="final">Final price charged to the client (₪)</label>
          <input id="final" className="input text-lg font-semibold" inputMode="decimal" type="number" min="1" step="0.01" value={finalPrice} onChange={(e) => setFinalPrice(e.target.value)} required />
        </div>
        <div className="space-y-1 rounded-xl bg-slate-50 p-3 text-sm">
          <div className="flex justify-between"><span className="text-slate-500">Estimate</span><span>{formatILS(job.estimatedPrice)}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Fee held</span><span>{formatILS(job.platformFee)}</span></div>
          <div className="flex justify-between font-semibold"><span>Platform fee ({Math.round(feeRate * 100)}%)</span><span>{formatILS(fee)}</span></div>
        </div>
        {underpriced && (
          <p className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
            This is under half the estimate. The job will be sent for review and your fee stays held until it is resolved.
          </p>
        )}
        {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
        <button className="btn-success w-full py-3" disabled={busy || code.length !== 4 || !validPrice}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Verify &amp; complete
        </button>
      </form>
    </Modal>
  );
}
