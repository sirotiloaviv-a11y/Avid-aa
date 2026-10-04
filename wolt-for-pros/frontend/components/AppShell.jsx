'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LogOut, Wrench } from 'lucide-react';
import { useSession } from '@/lib/session';

const ROLE_LABEL = { client: 'Client', tradesperson: 'Pro', admin: 'Admin' };

export default function AppShell({ children = null, actions = null }) {
  const { user, logout } = useSession();
  const router = useRouter();

  return (
    <div className="min-h-screen pb-10">
      <header className="sticky top-[var(--demo-bar-h,0px)] z-[500] border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-3 px-4">
          <Link href="/" className="flex items-center gap-2 font-extrabold tracking-tight">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Wrench className="h-4 w-4" />
            </span>
            <span>Wolt for Pros</span>
          </Link>
          <div className="flex items-center gap-2">
            {actions}
            {user && (
              <>
                <span className="hidden text-sm text-slate-600 sm:inline">
                  {user.name} · <span className="font-medium">{ROLE_LABEL[user.role]}</span>
                </span>
                <button
                  type="button"
                  className="rounded-full p-2 text-slate-500 hover:bg-slate-100"
                  onClick={() => {
                    logout();
                    router.replace('/');
                  }}
                  aria-label="Log out"
                  title="Log out"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 pt-5">{children}</main>
    </div>
  );
}
