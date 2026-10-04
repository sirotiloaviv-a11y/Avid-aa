import { useMemo, useState } from 'react';
import { useVeyra } from '../lib/VeyraContext.jsx';
import { SEVERITIES, SEVERITY_STYLE, timeAgo } from '../lib/format.js';
import { Icon, Spinner } from './Icon.jsx';
import { EmptyState, ProviderMark, SeverityBadge } from './primitives.jsx';

const EXPOSURE_LABEL = { public: 'Internet-exposed', external: 'External access', internal: 'Internal' };

export function RecommendationCard({ rec, index }) {
  const { actions, busy } = useVeyra();
  const [open, setOpen] = useState(false);
  const remediating = rec.status === 'remediating' || busy[`remediate:${rec.findingId}`];
  const style = SEVERITY_STYLE[rec.severity];

  return (
    <li
      className={`group relative animate-fade-up overflow-hidden rounded-xl border bg-ink-850/60 transition hover:border-white/[0.12] ${
        remediating ? 'border-brand-400/30' : 'border-white/[0.06]'
      }`}
      style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
    >
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: style.bar }} aria-hidden="true" />
      <div className="flex flex-col gap-4 p-4 pl-5 sm:flex-row sm:items-start">
        <div className="hidden w-7 shrink-0 pt-0.5 text-center font-mono text-sm text-slate-600 sm:block">{String(rec.rank).padStart(2, '0')}</div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={rec.severity} />
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
              <ProviderMark integration={rec.integration} size="sm" />
              {rec.integration.name}
            </span>
            <span className="text-xs text-slate-600">·</span>
            <span className="text-xs text-slate-500">{rec.category}</span>
            {rec.exposure !== 'internal' && (
              <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                <Icon name="globe" className="h-3 w-3" /> {EXPOSURE_LABEL[rec.exposure]}
              </span>
            )}
          </div>

          <h3 className="mt-2 text-[15px] font-semibold leading-snug text-slate-100">{rec.title}</h3>
          <p className={`mt-1.5 text-sm leading-relaxed text-slate-400 ${open ? '' : 'line-clamp-2'}`}>{rec.explanation}</p>

          {open && (
            <div className="mt-4 grid gap-4 rounded-lg border border-white/[0.06] bg-ink-950/50 p-4 md:grid-cols-2">
              <div>
                <p className="eyebrow">Business impact</p>
                <p className="mt-1.5 text-sm text-slate-300">{rec.impact}</p>
                <p className="eyebrow mt-4">Affected resource</p>
                <p className="mt-1.5 break-all font-mono text-xs text-slate-300">{rec.resource.name}</p>
                <p className="text-xs text-slate-500">{rec.resource.type}</p>
                {rec.frameworks?.length > 0 && (
                  <>
                    <p className="eyebrow mt-4">Compliance</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {rec.frameworks.map((f) => (
                        <span key={f} className="rounded border border-white/10 px-1.5 py-0.5 text-[11px] text-slate-400">{f}</span>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <div>
                <p className="eyebrow">Remediation playbook</p>
                <ol className="mt-2 space-y-2">
                  {rec.remediation.map((step, i) => (
                    <li key={step} className="flex gap-2.5 text-sm text-slate-300">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/[0.06] font-mono text-[10px] text-slate-400">{i + 1}</span>
                      {step}
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <button type="button" onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1 font-medium text-slate-400 hover:text-brand-300" aria-expanded={open}>
              <Icon name="chevronDown" className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
              {open ? 'Hide details' : 'Details & playbook'}
            </button>
            <span className="inline-flex items-center gap-1"><Icon name="clock" className="h-3 w-3" /> Detected {timeAgo(rec.detectedAt)}</span>
            <span className="inline-flex items-center gap-1"><Icon name="wrench" className="h-3 w-3" /> ~{rec.effort} to fix</span>
          </div>
        </div>

        <div className="flex shrink-0 flex-row items-center justify-between gap-3 sm:w-40 sm:flex-col sm:items-end">
          {rec.projectedGain > 0 && (
            <div className="text-right">
              <p className="tabular font-mono text-lg font-semibold text-emerald-400">+{rec.projectedGain}</p>
              <p className="text-[11px] text-slate-500">score if fixed</p>
            </div>
          )}
          <button
            type="button"
            className={remediating ? 'btn-secondary w-full max-w-[10rem] text-brand-300' : 'btn-primary w-full max-w-[10rem]'}
            disabled={remediating}
            onClick={() => actions.remediate(rec)}
          >
            {remediating ? <><Spinner className="h-4 w-4" /> Remediating…</> : <><Icon name="bolt" className="h-4 w-4" /> Remediate</>}
          </button>
        </div>
      </div>
      {remediating && <div className="h-0.5 w-full overflow-hidden bg-brand-500/10"><div className="h-full w-1/3 animate-shimmer bg-brand-400" /></div>}
    </li>
  );
}

export function RecommendationsFeed({ recommendations, integrations, limit, showFilters = false, onViewAll }) {
  const [severity, setSeverity] = useState('');
  const [provider, setProvider] = useState('');

  const filtered = useMemo(
    () => recommendations.filter((r) => (!severity || r.severity === severity) && (!provider || r.integration.id === provider)),
    [recommendations, severity, provider],
  );
  const visible = limit ? filtered.slice(0, limit) : filtered;
  const counts = useMemo(() => Object.fromEntries(SEVERITIES.map((s) => [s, recommendations.filter((r) => r.severity === s).length])), [recommendations]);

  return (
    <section className="card">
      <div className="card-header flex-wrap">
        <div className="flex items-center gap-3">
          <span className="rounded-lg bg-gradient-to-br from-brand-500/20 to-indigo-500/20 p-2 text-brand-300 ring-1 ring-brand-400/20">
            <Icon name="sparkles" className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Security Brain Recommendations</h2>
            <p className="text-xs text-slate-500">Ranked by severity, exposure and exploitability across every connected source</p>
          </div>
        </div>
        {onViewAll && recommendations.length > (limit ?? Infinity) && (
          <button type="button" onClick={onViewAll} className="btn-ghost text-xs">
            View all {recommendations.length} <Icon name="chevronRight" className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {showFilters && (
        <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-5 py-3">
          <button type="button" onClick={() => setSeverity('')} className={`chip ${!severity ? 'border-brand-400/40 bg-brand-500/10 text-brand-200' : 'border-white/10 text-slate-400 hover:text-slate-200'}`}>
            All <span className="tabular text-slate-500">{recommendations.length}</span>
          </button>
          {SEVERITIES.filter((s) => counts[s] > 0).map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => setSeverity(severity === s ? '' : s)}
              className={`chip ${severity === s ? `${SEVERITY_STYLE[s].border} ${SEVERITY_STYLE[s].bg} ${SEVERITY_STYLE[s].text}` : 'border-white/10 text-slate-400 hover:text-slate-200'}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${SEVERITY_STYLE[s].dot}`} />
              {SEVERITY_STYLE[s].label} <span className="tabular opacity-70">{counts[s]}</span>
            </button>
          ))}
          <select value={provider} onChange={(e) => setProvider(e.target.value)} className="input ml-auto w-auto py-1.5 text-xs" aria-label="Filter by integration">
            <option value="">All integrations</option>
            {integrations.filter((i) => i.monitored).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </div>
      )}

      {visible.length === 0 ? (
        <EmptyState
          icon={<Icon name="shieldCheck" className="h-6 w-6" />}
          title={recommendations.length ? 'Nothing matches these filters' : 'No open recommendations'}
          body={recommendations.length ? 'Clear the filters to see every recommendation.' : 'Every issue across your monitored integrations has been remediated.'}
        />
      ) : (
        <ul className="space-y-3 p-4">
          {visible.map((rec, i) => <RecommendationCard key={rec.findingId} rec={rec} index={i} />)}
        </ul>
      )}
    </section>
  );
}
