'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { currentMode, onModeChange, resolveMode } from './mode.js';
import { demoSocket, isDemoDriving, resetDemo, toggleDemoDrive } from './mockServer.js';
import { closeSocket } from '../socket.js';
import { useToast } from '@/components/ui/Toast';

// Global demo state: whether the app runs against the in-browser mock, the
// driver simulations in flight, and the "epoch" that remounts pages after a
// role switch, a reset, or a fall-back from a live backend.
const DemoContext = createContext(null);

export function DemoProvider({ children = null }) {
  const toast = useToast();
  const [mode, setMode] = useState(currentMode());
  const [epoch, setEpoch] = useState(0);
  const [driving, setDriving] = useState({}); // jobId -> true while the mock drives

  const bumpEpoch = useCallback(() => setEpoch((e) => e + 1), []);

  useEffect(() => {
    resolveMode().then(setMode);
    return onModeChange((next) => {
      closeSocket();
      setMode(next);
      setEpoch((e) => e + 1);
      toast('Cannot reach the server. You are now in demo mode with sample data.', 'info', 7000);
    });
  }, [toast]);

  useEffect(() => {
    if (mode !== 'demo') return undefined;
    const onDrive = ({ jobId, active, arrived }) => {
      setDriving((d) => ({ ...d, [jobId]: active }));
      if (arrived) toast('The tradesperson has arrived at the client.', 'success');
    };
    demoSocket.on('demo:drive', onDrive);
    return () => demoSocket.off('demo:drive', onDrive);
  }, [mode, toast]);

  const toggleDrive = useCallback((jobId) => {
    const active = toggleDemoDrive(jobId);
    setDriving((d) => ({ ...d, [jobId]: active }));
    return active;
  }, []);

  const isDriving = useCallback((jobId) => Boolean(driving[jobId] ?? isDemoDriving(jobId)), [driving]);

  const reset = useCallback(() => {
    resetDemo();
    setDriving({});
    setEpoch((e) => e + 1);
  }, []);

  const value = useMemo(
    () => ({ mode, isDemo: mode === 'demo', epoch, bumpEpoch, isDriving, toggleDrive, reset }),
    [mode, epoch, bumpEpoch, isDriving, toggleDrive, reset],
  );
  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo() {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error('useDemo must be used inside DemoProvider');
  return ctx;
}
