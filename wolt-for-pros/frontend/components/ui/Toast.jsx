'use client';

import { createContext, useCallback, useContext, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';

const ToastContext = createContext(null);

const STYLES = {
  success: { icon: CheckCircle2, className: 'bg-emerald-600' },
  error: { icon: AlertTriangle, className: 'bg-rose-600' },
  info: { icon: Info, className: 'bg-slate-900' },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), []);

  const toast = useCallback((message, type = 'info', durationMs = 4500) => {
    const id = nextId.current++;
    setToasts((list) => [...list.slice(-3), { id, message, type }]);
    setTimeout(() => dismiss(id), durationMs);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-3 z-[1000] flex flex-col items-center gap-2 px-4">
        {toasts.map((t) => {
          const { icon: Icon, className } = STYLES[t.type] || STYLES.info;
          return (
            <div key={t.id} role="status" className={`pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-xl px-4 py-3 text-sm text-white shadow-lg ${className}`}>
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="flex-1">{t.message}</span>
              <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss" className="opacity-80 hover:opacity-100">
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside ToastProvider');
  return ctx;
}
