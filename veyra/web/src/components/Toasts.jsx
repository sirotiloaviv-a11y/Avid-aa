import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon.jsx';

const ToastContext = createContext(null);

const TONES = {
  success: { icon: 'check', ring: 'border-emerald-500/30', iconClass: 'text-emerald-400 bg-emerald-500/10' },
  error: { icon: 'alert', ring: 'border-rose-500/30', iconClass: 'text-rose-400 bg-rose-500/10' },
  info: { icon: 'sparkles', ring: 'border-brand-400/30', iconClass: 'text-brand-300 bg-brand-500/10' },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), []);

  const push = useCallback((toast) => {
    const id = nextId.current++;
    setToasts((list) => [...list.slice(-3), { id, tone: 'info', ...toast }]);
    setTimeout(() => dismiss(id), toast.tone === 'error' ? 7000 : 4500);
  }, [dismiss]);

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-6" aria-live="polite">
        {toasts.map((toast) => {
          const tone = TONES[toast.tone] ?? TONES.info;
          return (
            <div key={toast.id} className={`pointer-events-auto flex w-full max-w-sm animate-fade-up items-start gap-3 rounded-xl border ${tone.ring} bg-ink-850/95 p-3.5 shadow-2xl backdrop-blur`}>
              <span className={`mt-0.5 rounded-lg p-1.5 ${tone.iconClass}`}><Icon name={tone.icon} className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-100">{toast.title}</p>
                {toast.body && <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{toast.body}</p>}
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
