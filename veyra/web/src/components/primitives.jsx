import { SEVERITY_STYLE } from '../lib/format.js';

export function SeverityBadge({ severity, size = 'sm' }) {
  const style = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.low;
  const pad = size === 'xs' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border font-semibold uppercase tracking-wide ${pad} ${style.bg} ${style.border} ${style.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot} ${severity === 'critical' ? 'animate-pulse' : ''}`} />
      {style.label}
    </span>
  );
}

/** Monogram tile in the provider's accent colour (no third-party logos bundled). */
export function ProviderMark({ integration, size = 'md' }) {
  const sizes = { sm: 'h-6 w-6 text-[9px] rounded-md', md: 'h-9 w-9 text-[11px] rounded-lg', lg: 'h-12 w-12 text-sm rounded-xl' };
  const color = integration?.color ?? '#64748b';
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center font-bold tracking-tight text-white ${sizes[size]}`}
      style={{ background: `linear-gradient(135deg, ${color}, ${color}99)`, boxShadow: `0 0 0 1px ${color}55, 0 6px 18px -8px ${color}` }}
      aria-hidden="true"
    >
      {integration?.shortName ?? '?'}
    </span>
  );
}

export function Toggle({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        checked ? 'border-brand-400/50 bg-brand-500/80' : 'border-white/10 bg-ink-700'
      }`}
    >
      <span className={`inline-block h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-[22px]' : 'translate-x-[3px]'}`} />
    </button>
  );
}

export function StatusDot({ status }) {
  const styles = {
    connected: 'bg-emerald-400',
    syncing: 'bg-brand-400',
    connecting: 'bg-brand-400',
    paused: 'bg-amber-400',
    error: 'bg-rose-500',
    disconnected: 'bg-slate-600',
  };
  const live = status === 'connected' || status === 'syncing';
  return (
    <span className="relative inline-flex h-2 w-2">
      {live && <span className={`absolute inline-flex h-full w-full animate-pulse-ring rounded-full ${styles[status]}`} />}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${styles[status] ?? 'bg-slate-600'}`} />
    </span>
  );
}

export const STATUS_LABEL = {
  connected: 'Monitoring',
  syncing: 'Scanning…',
  connecting: 'Connecting…',
  paused: 'Paused',
  error: 'Error',
  disconnected: 'Not connected',
};

export function EmptyState({ icon, title, body, children }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-3 text-emerald-300">{icon}</div>
      <p className="font-medium text-slate-200">{title}</p>
      {body && <p className="mt-1 max-w-sm text-sm text-slate-500">{body}</p>}
      {children}
    </div>
  );
}

export function Skeleton({ className = '' }) {
  return <div className={`animate-pulse rounded-lg bg-white/[0.04] ${className}`} />;
}
