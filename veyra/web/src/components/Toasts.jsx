import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Icon, Spinner } from './Icon.jsx';

const ToastContext = createContext(null);

const TONES = {
  success: { icon: 'check', ring: 'border-emerald-500/30', iconClass: 'text-emerald-400 bg-emerald-500/10' },
  error: { icon: 'alert', ring: 'border-rose-500/30', iconClass: 'text-rose-400 bg-rose-500/10' },
  info: { icon: 'sparkles', ring: 'border-brand-400/30', iconClass: 'text-brand-300 bg-brand-500/10' },
  progress: { icon: null, ring: 'border-brand-400/40', iconClass: 'text-brand-300 bg-brand-500/10' },
};

const defaultLifetime = (toast) => (toast.persistent ? null : toast.tone === 'error' ? 7000 : 4500);

/**
 * Toasts can be fire-and-forget (`push`) or long-lived and updated in place
 * (`push({ persistent: true })` then `update(id, patch)`), which is how the
 * Auto-Fix progress toast streams its steps.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const schedule = useCallback((id, ms) => {
    clearTimeout(timers.current.get(id));
    if (ms) timers.current.set(id, setTimeout(() => dismiss(id), ms));
  }, [dismiss]);

  const push = useCallback((toast) => {
    const id = nextId.current++;
    setToasts((list) => {
      // Keep at most 4 toasts, never evicting one that is still in progress.
      const removable = list.filter((t) => !t.persistent);
      const overflow = Math.max(0, list.length - 3);
      const evict = new Set(removable.slice(0, overflow).map((t) => t.id));
      return [...list.filter((t) => !evict.has(t.id)), { id, tone: 'info', ...toast }];
    });
    schedule(id, toast.dismissAfter ?? defaultLifetime(toast));
    return id;
  }, [schedule]);

  const update = useCallback((id, patch) => {
    setToasts((list) => list.map((t) => (t.id === id ? { ...t, ...patch } : t)));
    if ('dismissAfter' in patch || patch.persistent === false) schedule(id, patch.dismissAfter ?? defaultLifetime(patch));
  }, [schedule]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const value = useMemo(() => ({ push, update, dismiss }), [push, update, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-6" aria-live="polite">
        {toasts.map((toast) => {
          const tone = TONES[toast.tone] ?? TONES.info;
          return (
            <div key={toast.id} role="status" className={`pointer-events-auto flex w-full max-w-sm animate-fade-up items-start gap-3 rounded-xl border ${tone.ring} bg-ink-850/95 p-3.5 shadow-2xl backdrop-blur sm:w-96`}>
              <span className={`mt-0.5 rounded-lg p-1.5 ${tone.iconClass}`}>
                {tone.icon ? <Icon name={tone.icon} className="h-4 w-4" /> : <Spinner className="h-4 w-4" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-100">{toast.title}</p>
                {toast.body && <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{toast.body}</p>}
                {toast.content}
              </div>
              <button type="button" onClick={() => dismiss(toast.id)} className="rounded p-1 text-slate-500 hover:text-slate-200" aria-label="Dismiss">
                <Icon name="x" className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside <ToastProvider>');
  return context;
}
