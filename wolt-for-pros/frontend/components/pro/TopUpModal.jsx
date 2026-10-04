'use client';

import { useState } from 'react';
import { CreditCard, Loader2 } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatILS } from '@/lib/format';

const DEFAULT_PRESETS = [100, 200, 500];

export default function TopUpModal({ open, onClose, onCredited, presets = DEFAULT_PRESETS, suggested }) {
  const toast = useToast();
  const [amount, setAmount] = useState(presets[1] || presets[0]);
  const [busy, setBusy] = useState(false);

  async function pay() {
    setBusy(true);
    try {
      const session = await api('/api/wallet/checkout-session', { method: 'POST', body: { amount } });
      if (session.url) {
        // Stripe Checkout; it redirects back to /pro?topup=success.
        window.location.assign(session.url);
        return;
      }
      if (session.mock) {
        // No Stripe key on the server: test mode credits directly.
        const data = await api('/api/wallet/deposit', { method: 'POST', body: { amount } });
        toast(`${formatILS(amount)} added to your wallet (test mode)`, 'success');
        onCredited(data.wallet);
        onClose();
      }
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Top up your wallet"
      footer={
        <button type="button" className="btn-primary w-full py-3" onClick={pay} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
          Pay {formatILS(amount)}
        </button>
      }
    >
      {suggested ? (
        <p className="mb-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
          You need at least {formatILS(suggested)} more to accept that job.
        </p>
      ) : null}
      <div className="grid grid-cols-3 gap-2">
        {presets.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setAmount(p)}
            className={`rounded-2xl py-4 text-lg font-extrabold ring-1 transition ${amount === p ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white ring-slate-200 hover:ring-brand-300'}`}
          >
            ₪{p}
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-500">
        Secure card payment by Stripe. Credit is used only for platform fees and never expires.
      </p>
    </Modal>
  );
}
