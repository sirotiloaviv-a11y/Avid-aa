'use client';

import { Fragment } from 'react';
import { useDemo } from '@/lib/demo/DemoContext';

// Remounts the page when the demo epoch changes (role switch, reset, or a
// fall-back from a live backend) so every screen refetches.
export default function DemoRemount({ children = null }) {
  const { epoch } = useDemo();
  return <Fragment key={epoch}>{children}</Fragment>;
}
