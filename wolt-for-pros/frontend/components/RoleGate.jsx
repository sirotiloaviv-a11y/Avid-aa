'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { HOME_BY_ROLE, useSession } from '@/lib/session';
import { useDemo } from '@/lib/demo/DemoContext';
import Spinner from './ui/Spinner';

export default function RoleGate({ role, children = null }) {
  const { user, loading, loginAsRole } = useSession();
  const { isDemo: demo } = useDemo();
  const router = useRouter();
  const switching = useRef(false);

  useEffect(() => {
    if (loading) return;
    // Demo mode: opening /client, /pro or /admin signs in as that role's
    // seeded account instead of bouncing to the login page.
    if (demo && (!user || user.role !== role)) {
      if (switching.current) return;
      switching.current = true;
      loginAsRole(role).catch(() => router.replace('/')).finally(() => {
        switching.current = false;
      });
      return;
    }
    if (!user) router.replace('/');
  }, [loading, user, role, demo, loginAsRole, router]);

  if (loading || !user || (demo && user.role !== role)) return <Spinner />;
  if (user.role !== role) {
    return (
      <div className="mx-auto max-w-md p-6 text-center">
        <p className="mb-4 text-slate-600">This page is for a different account type.</p>
        <Link className="btn-primary" href={HOME_BY_ROLE[user.role] || '/'}>Go to my dashboard</Link>
      </div>
    );
  }
  return children;
}
