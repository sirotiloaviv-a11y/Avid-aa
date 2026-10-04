'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { FlaskConical, HardHat, Loader2, RotateCcw, ShieldCheck, User } from 'lucide-react';
import { HOME_BY_ROLE, useSession } from '@/lib/session';
import { useDemo } from '@/lib/demo/DemoContext';
import { useToast } from '@/components/ui/Toast';

const BAR_HEIGHT = '48px';

const VIEWS = [
  { role: 'client', label: 'Client View', icon: User, path: '/client' },
  { role: 'tradesperson', label: 'Tradesperson Dashboard', short: 'Pro', icon: HardHat, path: '/pro' },
  { role: 'admin', label: 'Admin Dispute Panel', short: 'Admin', icon: ShieldCheck, path: HOME_BY_ROLE.admin },
];

// Floating bar pinned to the top while the app runs on the in-browser mock.
export default function DemoToolbar() {
  const { isDemo, reset } = useDemo();
  const { user, refresh } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const [resetting, setResetting] = useState(false);

  // Lets the sticky app header and toasts sit below the bar.
  useEffect(() => {
    const root = document.documentElement;
    if (isDemo) root.style.setProperty('--demo-bar-h', BAR_HEIGHT);
    return () => root.style.removeProperty('--demo-bar-h');
  }, [isDemo]);

  if (!isDemo) return null;

  async function onReset() {
    setResetting(true);
    try {
      reset();
      await refresh();
      toast('Demo data reset', 'success');
    } finally {
      setResetting(false);
    }
  }

  return (
    <>
      <div aria-hidden="true" style={{ height: BAR_HEIGHT }} />
      <div className="fixed inset-x-0 top-0 z-[800] flex h-12 items-center justify-center bg-slate-900/95 px-2 text-white shadow-lg backdrop-blur">
        <nav aria-label="Demo views" className="flex max-w-full items-center gap-1 overflow-x-auto">
          <span className="hidden items-center gap-1.5 px-2 text-[11px] font-bold uppercase tracking-wider text-amber-300 md:flex" title="No backend connected: sample data lives in this browser">
            <FlaskConical className="h-3.5 w-3.5" /> Demo
          </span>
          {VIEWS.map((view) => {
            const Icon = view.icon;
            const section = view.path.split('/').slice(0, 2).join('/');
            const current = user && user.role === view.role && pathname.startsWith(section);
            return (
              // Navigate only: the destination's RoleGate signs in as that
              // role's demo account. Logging in first would remount the
              // current page, whose RoleGate would switch straight back.
              <button
                key={view.role}
                type="button"
                onClick={() => router.push(view.path)}
                aria-current={current ? 'page' : undefined}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:text-sm ${
                  current ? 'bg-white text-slate-900' : 'text-slate-200 hover:bg-white/10'
                }`}
              >
                <Icon className="h-4 w-4" />
                <span className="sm:hidden">{view.short || view.label}</span>
                <span className="hidden sm:inline">{view.label}</span>
              </button>
            );
          })}
          <span className="mx-1 h-6 w-px shrink-0 bg-white/15" />
          <button
            type="button"
            onClick={onReset}
            disabled={resetting}
            className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 sm:text-sm"
          >
            {resetting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            <span className="sm:hidden">Reset</span>
            <span className="hidden sm:inline">Reset Demo Data</span>
          </button>
        </nav>
      </div>
    </>
  );
}
