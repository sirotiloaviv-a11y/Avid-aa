'use client';

import { useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { FlaskConical, HardHat, Loader2, RotateCcw, ShieldCheck, User } from 'lucide-react';
import { HOME_BY_ROLE, useSession } from '@/lib/session';
import { useToast } from '@/components/ui/Toast';

const VIEWS = [
  { role: 'client', label: 'Switch to Client View', short: 'Client', icon: User, path: '/client' },
  { role: 'tradesperson', label: 'Switch to Tradesperson Dashboard', short: 'Pro', icon: HardHat, path: '/pro' },
  { role: 'admin', label: 'Switch to Admin Panel', short: 'Admin', icon: ShieldCheck, path: HOME_BY_ROLE.admin },
];

// Floating preview bar, rendered only when the app runs against the
// in-browser mock (no backend reachable, or NEXT_PUBLIC_DEMO_MODE=true).
export default function DemoToolbar() {
  const { mode, user, resetDemoData } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const [busy, setBusy] = useState(null);

  if (mode !== 'demo') return null;

  // Navigate only: the destination's RoleGate signs in as that role's demo
  // account. Logging in first would remount the current page, whose RoleGate
  // would then switch straight back to its own role.
  function switchTo(view) {
    router.push(view.path);
  }

  async function reset() {
    setBusy('reset');
    try {
      await resetDemoData();
      toast('Demo data reset', 'success');
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {/* Keeps page content clear of the floating bar. */}
      <div aria-hidden="true" className="h-24" />
      <div className="fixed inset-x-0 bottom-3 z-[800] flex justify-center px-3">
        <nav
          aria-label="Demo preview"
          className="flex max-w-full items-center gap-1 overflow-x-auto rounded-2xl bg-slate-900/95 p-1.5 text-white shadow-2xl ring-1 ring-white/10 backdrop-blur"
        >
          <span className="hidden items-center gap-1.5 px-2 text-[11px] font-bold uppercase tracking-wider text-amber-300 sm:flex" title="No backend connected: data lives in this browser">
            <FlaskConical className="h-3.5 w-3.5" /> Demo
          </span>
          {VIEWS.map((view) => {
            const Icon = view.icon;
            const current = user && user.role === view.role && pathname.startsWith(view.path.split('/').slice(0, 2).join('/'));
            return (
              <button
                key={view.role}
                type="button"
                onClick={() => switchTo(view)}
                disabled={Boolean(busy)}
                title={view.label}
                aria-current={current ? 'page' : undefined}
                className={`flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition sm:text-sm ${
                  current ? 'bg-white text-slate-900' : 'text-slate-200 hover:bg-white/10'
                }`}
              >
                <Icon className="h-4 w-4" />
                <span className="sm:hidden">{view.short}</span>
                <span className="hidden sm:inline">{view.label}</span>
              </button>
            );
          })}
          <span className="mx-0.5 h-6 w-px shrink-0 bg-white/15" />
          <button
            type="button"
            onClick={reset}
            disabled={Boolean(busy)}
            title="Reset Demo Data"
            className="flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 sm:text-sm"
          >
            {busy === 'reset' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            <span className="sm:hidden">Reset</span>
            <span className="hidden sm:inline">Reset Demo Data</span>
          </button>
        </nav>
      </div>
    </>
  );
}
