import { Icon, Spinner } from './Icon.jsx';

const STEP_ICON = {
  done: <Icon name="check" className="h-3 w-3 text-emerald-400" strokeWidth={2.4} />,
  running: <Spinner className="h-3 w-3 text-brand-300" />,
  failed: <Icon name="x" className="h-3 w-3 text-rose-400" strokeWidth={2.4} />,
  skipped: <span className="block h-[2px] w-2 rounded bg-slate-600" />,
  pending: <span className="block h-1.5 w-1.5 rounded-full bg-slate-600" />,
};

/** Step-by-step Auto-Fix progress, rendered inside a toast. */
export function AutoFixProgress({ job }) {
  if (!job?.steps) return null;
  const active = job.steps.find((s) => s.status === 'running') ?? [...job.steps].reverse().find((s) => s.detail);
  const done = job.steps.filter((s) => s.status === 'done').length;

  return (
    <div className="mt-2.5">
      <div className="mb-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${job.status === 'failed' ? 'bg-rose-500' : 'bg-gradient-to-r from-brand-500 to-emerald-400'}`}
          style={{ width: `${(done / job.steps.length) * 100}%` }}
        />
      </div>
      <ol className="space-y-1.5">
        {job.steps.map((step) => (
          <li key={step.key} className="flex items-center gap-2 text-xs">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white/[0.04]">{STEP_ICON[step.status]}</span>
            <span className={
              step.status === 'running' ? 'font-medium text-slate-100'
                : step.status === 'done' ? 'text-slate-300'
                  : step.status === 'failed' ? 'text-rose-300' : 'text-slate-500'
            }>
              {step.label}
            </span>
          </li>
        ))}
      </ol>
      {active?.detail && (
        <p className="mt-2 line-clamp-3 break-words rounded-md bg-ink-950/60 px-2 py-1.5 font-mono text-[10.5px] leading-relaxed text-slate-400">
          {active.detail}
        </p>
      )}
    </div>
  );
}
