import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { useToast } from '../components/Toasts.jsx';

const VeyraContext = createContext(null);

const IDLE_POLL_MS = 15000;
const ACTIVE_POLL_MS = 1200;

/**
 * Single source of truth for the dashboard. Everything is derived from one
 * GET /api/dashboard call; while a remediation is running we poll quickly so
 * the score animates up as soon as the backend resolves the finding.
 */
export function VeyraProvider({ children }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState({});
  const inFlight = useRef(null);

  const refresh = useCallback(async () => {
    if (inFlight.current) return inFlight.current;
    inFlight.current = api.dashboard()
      .then((next) => {
        setData(next);
        setError(null);
        return next;
      })
      .catch((e) => {
        setError(e);
        return null;
      })
      .finally(() => {
        inFlight.current = null;
      });
    return inFlight.current;
  }, []);

  const remediating = data?.activity?.remediating ?? 0;
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, remediating > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(interval);
  }, [refresh, remediating]);

  // Wrap an action so the UI can show per-item spinners and errors become toasts.
  const run = useCallback(async (key, action, { success, rethrow = false } = {}) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const result = await action();
      if (success) toast.push({ tone: 'success', ...(typeof success === 'function' ? success(result) : success) });
      await refresh();
      return result;
    } catch (e) {
      if (rethrow) throw e;
      toast.push({ tone: 'error', title: 'Action failed', body: e.message });
      return null;
    } finally {
      setBusy((b) => {
        const { [key]: _, ...rest } = b;
        return rest;
      });
    }
  }, [refresh, toast]);

  const actions = useMemo(() => ({
    refresh,
    remediate: (rec) => run(`remediate:${rec.findingId ?? rec.id}`, () => api.remediate(rec.findingId ?? rec.id), {
      success: { title: 'Remediation started', body: `Veyra is running the ${rec.integration?.name ?? ''} playbook for “${rec.title}”.` },
    }),
    connect: (integration, credentials) => run(`integration:${integration.id}`, () => api.connect(integration.id, credentials), {
      rethrow: true,
      success: (result) => ({
        title: `${integration.name} connected`,
        body: `First scan complete: ${result.findings.open} open finding${result.findings.open === 1 ? '' : 's'}.`,
      }),
    }),
    disconnect: (integration) => run(`integration:${integration.id}`, () => api.disconnect(integration.id), {
      success: { title: `${integration.name} disconnected`, body: 'Its findings were removed from your posture.' },
    }),
    setEnabled: (integration, enabled) => run(`toggle:${integration.id}`, () => api.setEnabled(integration.id, enabled), {
      success: { title: enabled ? `Monitoring resumed for ${integration.name}` : `Monitoring paused for ${integration.name}` },
    }),
    sync: (integration) => run(`integration:${integration.id}`, () => api.sync(integration.id), {
      success: { title: `${integration.name} rescanned` },
    }),
    syncAll: () => run('syncAll', api.syncAll, { success: { title: 'All integrations rescanned' } }),
    reset: () => run('reset', api.reset, { success: { title: 'Demo data reset' } }),
  }), [refresh, run]);

  const value = useMemo(() => ({ data, error, busy, actions }), [data, error, busy, actions]);
  return <VeyraContext.Provider value={value}>{children}</VeyraContext.Provider>;
}

export function useVeyra() {
  const context = useContext(VeyraContext);
  if (!context) throw new Error('useVeyra must be used inside <VeyraProvider>');
  return context;
}
