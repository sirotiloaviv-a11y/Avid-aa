'use client';

import { Fragment } from 'react';
import { useSession } from '@/lib/session';

// Remounts the page when demo data is reset or the demo role changes, so
// every screen refetches from the fresh mock state.
export default function DemoRemount({ children }) {
  const { epoch } = useSession();
  return <Fragment key={epoch}>{children}</Fragment>;
}
