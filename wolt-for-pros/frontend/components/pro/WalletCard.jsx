'use client';

import { useEffect, useRef, useState } from 'react';
import { Lock, Plus, Wallet, Zap } from 'lucide-react';
import { formatILS } from '@/lib/format';

// Tweens a number towards its new value. Jumps straight to the first real
// value so the initial load doesn't count up from zero.
function useAnimatedNumber(value, duration = 800) {
  const [display, setDisplay] = useState(value);
  const shownRef = useRef(value);

  useEffect(() => {
    if (value == null) return undefined;
    const from = shownRef.current;
    if (from == null || from === value) {
      shownRef.current = value;
      setDisplay(value);
      return undefined;
    }
    const start = performance.now();
    let raf;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      const v = from + (value - from) * eased;
      shownRef.current = v;
      setDisplay(v);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return display;
}

// "+₪100" chips that float up whenever the balance grows.
function useIncreaseChips(value) {
  const [chips, setChips] = useState([]);
  const prev = useRef(value);
  const nextId = useRef(1);
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (before == null || value == null || value <= before) return;
    const id = nextId.current++;
    setChips((c) => [...c, { id, amount: value - before }]);
    // Not cleared on re-run: every chip must expire even if the balance
    // changes again before it finishes.
    setTimeout(() => setChips((c) => c.filter((x) => x.id !== id)), 1800);
  }, [value]);
  return chips;
}

export default function WalletCard({ wallet, feeRate, onTopUp, onQuickTopUp, quickAmount = 100, quickBusy = false }) {
  const balance = wallet ? wallet.balance : null;
  const locked = wallet ? wallet.lockedBalance : null;
  const shownBalance = useAnimatedNumber(balance);
  const shownLocked = useAnimatedNumber(locked);
  const chips = useIncreaseChips(balance);
  const negative = balance != null && balance < 0;

  return (
    <div
      key={chips.length ? chips[chips.length - 1].id : 0}
      className={`relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 to-brand-900 p-5 text-white shadow-card ${chips.length ? 'animate-wallet-glow' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <Wallet className="h-4 w-4" /> Fee wallet
        </p>
        <div className="flex gap-1.5">
          {onQuickTopUp && (
            <button
              type="button"
              onClick={onQuickTopUp}
              disabled={quickBusy}
              className="inline-flex items-center gap-1 rounded-full bg-emerald-400 px-3 py-1.5 text-xs font-bold text-slate-900 hover:bg-emerald-300 disabled:opacity-60"
            >
              <Zap className="h-3.5 w-3.5" /> Top Up ₪{quickAmount}
            </button>
          )}
          <button type="button" onClick={onTopUp} className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1.5 text-xs font-bold text-slate-900 hover:bg-brand-50">
            <Plus className="h-3.5 w-3.5" /> Other
          </button>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="relative">
          <p className="text-xs uppercase tracking-wide text-slate-400">Available balance</p>
          <p className={`text-3xl font-extrabold tabular-nums ${negative ? 'text-rose-300' : ''}`}>{formatILS(shownBalance ?? 0)}</p>
          {chips.map((chip) => (
            <span key={chip.id} className="animate-float-up pointer-events-none absolute -top-1 right-0 rounded-full bg-emerald-400 px-2 py-0.5 text-xs font-bold text-slate-900">
              +{formatILS(chip.amount)}
            </span>
          ))}
        </div>
        <div>
          <p className="flex items-center gap-1 text-xs uppercase tracking-wide text-slate-400">
            <Lock className="h-3 w-3" /> Locked balance
          </p>
          <p className="text-3xl font-extrabold tabular-nums text-slate-300">{formatILS(shownLocked ?? 0)}</p>
        </div>
      </div>
      <p className="mt-4 text-xs text-slate-400">
        {feeRate ? `${Math.round(feeRate * 100)}% platform fee is held when you accept a job and charged on the final price when the client gives you their code.` : ''}
        {negative && ' Your balance is negative: top up to accept new jobs.'}
      </p>
    </div>
  );
}
