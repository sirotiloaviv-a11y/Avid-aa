import { Lock, Plus, Wallet } from 'lucide-react';
import { formatILS } from '@/lib/format';

export default function WalletCard({ wallet, feeRate, onTopUp }) {
  const balance = wallet ? wallet.balance : 0;
  const locked = wallet ? wallet.lockedBalance : 0;
  const negative = balance < 0;
  return (
    <div className="overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 to-brand-900 p-5 text-white shadow-card">
      <div className="flex items-start justify-between">
        <p className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <Wallet className="h-4 w-4" /> Fee wallet
        </p>
        <button type="button" onClick={onTopUp} className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1.5 text-xs font-bold text-slate-900 hover:bg-brand-50">
          <Plus className="h-3.5 w-3.5" /> Top up
        </button>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400">Available balance</p>
          <p className={`text-3xl font-extrabold tabular-nums ${negative ? 'text-rose-300' : ''}`}>{formatILS(balance)}</p>
        </div>
        <div>
          <p className="flex items-center gap-1 text-xs uppercase tracking-wide text-slate-400">
            <Lock className="h-3 w-3" /> Locked balance
          </p>
          <p className="text-3xl font-extrabold tabular-nums text-slate-300">{formatILS(locked)}</p>
        </div>
      </div>
      <p className="mt-4 text-xs text-slate-400">
        {feeRate ? `${Math.round(feeRate * 100)}% platform fee is held when you accept a job and charged on the final price when the client gives you their code.` : ''}
        {negative && ' Your balance is negative: top up to accept new jobs.'}
      </p>
    </div>
  );
}
