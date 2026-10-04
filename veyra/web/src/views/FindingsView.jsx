import { Fragment, useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import { useVeyra } from '../lib/VeyraContext.jsx';
import { SEVERITIES, SEVERITY_STYLE, timeAgo } from '../lib/format.js';
import { Icon, Spinner } from '../components/Icon.jsx';
import { ProviderMark, SeverityBadge, Skeleton } from '../components/primitives.jsx';

const STATUS_STYLE = {
  open: 'text-slate-300 bg-white/[0.05] border-white/10',
  remediating: 'text-brand-300 bg-brand-500/10 border-brand-400/30',
  resolved: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
};

function useDebounced(value, ms) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export function FindingsView() {
  const { data, actions, busy } = useVeyra();
  const [filters, setFilters] = useState({ provider: '', severity: '', status: 'open' });
  const [query, setQuery] = useState('');
  const q = useDebounced(query, 250);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  // Refetch whenever filters change or the dashboard refreshes (remediation, sync…).
  useEffect(() => {
    let cancelled = false;
    api.findings({ ...filters, q })
      .then((r) => { if (!cancelled) { setResult(r); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [filters, q, data.generatedAt]);

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }));

  return (
    <section className="card">
      <div className="card-header flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">All findings</h2>
          <p className="text-xs text-slate-500">{result ? `${result.total} matching` : 'Loading…'}</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <label className="relative w-full sm:w-56">
            <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search findings…" className="input py-1.5 pl-8 text-xs" aria-label="Search findings" />
          </label>
          <select value={filters.severity} onChange={set('severity')} className="input w-auto py-1.5 text-xs" aria-label="Severity">
            <option value="">Any severity</option>
            {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY_STYLE[s].label}</option>)}
          </select>
          <select value={filters.provider} onChange={set('provider')} className="input w-auto py-1.5 text-xs" aria-label="Integration">
            <option value="">All integrations</option>
            {data.integrations.filter((i) => i.connected).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
          <select value={filters.status} onChange={set('status')} className="input w-auto py-1.5 text-xs" aria-label="Status">
            <option value="">Any status</option>
            <option value="open">Open</option>
            <option value="remediating">Remediating</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
      </div>

      {error && <p className="px-5 py-4 text-sm text-rose-300">{error.message}</p>}
      {!result && !error && <div className="space-y-2 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>}

      {result && (
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-5 py-3 font-medium">Severity</th>
                <th className="px-3 py-3 font-medium">Finding</th>
                <th className="px-3 py-3 font-medium">Source</th>
                <th className="px-3 py-3 font-medium">Detected</th>
                <th className="px-3 py-3 font-medium">Status</th>
                <th className="px-5 py-3 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {result.findings.length === 0 && (
                <tr><td colSpan={6} className="px-5 py-12 text-center text-sm text-slate-500">No findings match these filters.</td></tr>
              )}
              {result.findings.map((f) => {
                const isOpen = expanded === f.id;
                const working = f.status === 'remediating' || busy[`remediate:${f.id}`];
                return (
                  <Fragment key={f.id}>
                    <tr className={`cursor-pointer transition hover:bg-white/[0.02] ${!f.monitored ? 'opacity-50' : ''}`} onClick={() => setExpanded(isOpen ? null : f.id)}>
                      <td className="px-5 py-3 align-top"><SeverityBadge severity={f.severity} size="xs" /></td>
                      <td className="px-3 py-3 align-top">
                        <p className="font-medium text-slate-200">{f.title}</p>
                        <p className="mt-0.5 font-mono text-[11px] text-slate-500">{f.resource.type} · {f.resource.name}</p>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 align-top">
                        <span className="inline-flex items-center gap-2 text-xs text-slate-400"><ProviderMark integration={f.integration} size="sm" />{f.integration.name}</span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 align-top text-xs text-slate-500">{timeAgo(f.detectedAt)}</td>
                      <td className="px-3 py-3 align-top">
                        <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize ${STATUS_STYLE[f.status]}`}>
                          {f.status === 'remediating' && <Spinner className="h-3 w-3" />}
                          {f.status === 'resolved' && <Icon name="check" className="h-3 w-3" />}
                          {f.status}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right align-top">
                        {f.status !== 'resolved' && f.monitored && (
                          <button
                            type="button"
                            className="btn-secondary px-2.5 py-1 text-xs"
                            disabled={working}
                            onClick={(e) => { e.stopPropagation(); actions.remediate(f); }}
                          >
                            {working ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="bolt" className="h-3.5 w-3.5" />}
                            {working ? 'Running' : 'Remediate'}
                          </button>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-ink-950/40">
                        <td />
                        <td colSpan={5} className="px-3 pb-5 pt-1">
                          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">{f.explanation}</p>
                          <div className="mt-3 grid gap-4 md:grid-cols-2">
                            <div>
                              <p className="eyebrow">Remediation</p>
                              <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-xs text-slate-300">
                                {f.remediation.map((step) => <li key={step}>{step}</li>)}
                              </ol>
                            </div>
                            {Object.keys(f.evidence ?? {}).length > 0 && (
                              <div>
                                <p className="eyebrow">Evidence</p>
                                <pre className="scrollbar-thin mt-1.5 max-h-40 overflow-auto rounded-lg border border-white/[0.06] bg-ink-950 p-3 font-mono text-[11px] text-slate-400">{JSON.stringify(f.evidence, null, 2)}</pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
