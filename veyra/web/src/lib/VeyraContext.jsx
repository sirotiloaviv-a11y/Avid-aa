import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { useToast } from '../components/Toasts.jsx';
import { AutoFixProgress } from '../components/AutoFixProgress.jsx';

const VeyraContext = createContext(null);

const IDLE_POLL_MS = 15000;
const ACTIVE_POLL_MS = 1200;
const JOB_POLL_MS = 350;
const JOB_TIMEOUT_MS = 120000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const truncate = (text, max = 64) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

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

  /**
   * Auto-Fix: start the job, then poll it and stream each step into a toast.
   * The dashboard refreshes when the job finishes so the score animates up.
   */
  const autoFix = useCallback(async (rec) => {
    const findingId = rec.findingId ?? rec.id;
    const key = `autofix:${findingId}`;
    setBusy((b) => ({ ...b, [key]: true }));
    let toastId = null;
    try {
      let job = await api.startAutoFix(findingId);
      toastId = toast.push({
        tone: 'progress',
        persistent: true,
        title: `Auto-Fix: ${truncate(rec.title)}`,
        content: <AutoFixProgress job={job} />,
      });
      refresh();
      const deadline = Date.now() + JOB_TIMEOUT_MS;
      while (job.status === 'running' && Date.now() < deadline) {
        await sleep(JOB_POLL_MS);
        job = await api.autoFixJob(job.id);
        toast.update(toastId, { content: <AutoFixProgress job={job} /> });
      }
      await refresh();
      if (job.status === 'succeeded') {
        const delta = job.scoreAfter - job.scoreBefore;
        toast.update(toastId, {
          tone: 'success',
          persistent: false,
          dismissAfter: 7000,
          title: `Fixed: ${truncate(rec.title)}`,
          body: `Security score ${job.scoreBefore} → ${job.scoreAfter} (${delta >= 0 ? '+' : ''}${delta})`,
          content: <AutoFixProgress job={job} />,
        });
      } else {
        toast.update(toastId, {
          tone: 'error',
          persistent: false,
          dismissAfter: 9000,
          title: job.status === 'running' ? 'Auto-Fix is taking longer than expected' : 'Auto-Fix failed',
          body: job.error ?? 'Check the job status and try again.',
          content: <AutoFixProgress job={job} />,
        });
      }
      return job;
    } catch (e) {
      if (toastId) toast.update(toastId, { tone: 'error', persistent: false, title: 'Auto-Fix failed', body: e.message, content: null });
      else toast.push({ tone: 'error', title: 'Auto-Fix unavailable', body: e.message });
      refresh();
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
    autoFix,
    downloadReport: () => run('report', async () => {
      const { blob, filename } = await api.executiveReport();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return filename;
    }, { success: (filename) => ({ title: 'Executive report downloaded', body: filename }) }),
    remediate: (rec) => run(`remediate:${rec.findingId ?? rec.id}`, () => api.remediate(rec.findingId ?? rec.id), {
      success: { title: 'Marked for resolution', body: `“${truncate(rec.title)}” will be closed once the manual fix is confirmed.` },
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
  }), [refresh, run, autoFix]);

  const value = useMemo(() => ({ data, error, busy, actions }), [data, error, busy, actions]);
  return <VeyraContext.Provider value={value}>{children}</VeyraContext.Provider>;
}

export function useVeyra() {
  const context = useContext(VeyraContext);
  if (!context) throw new Error('useVeyra must be used inside <VeyraProvider>');
  return context;
}
