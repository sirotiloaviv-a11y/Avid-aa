'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { HOME_BY_ROLE, useSession } from '@/lib/session';
import Spinner from './ui/Spinner';

export default function RoleGate({ role, children }) {
  const { user, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  if (loading || !user) return <Spinner />;
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
