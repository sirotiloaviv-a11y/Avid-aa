import { useVeyra } from '../lib/VeyraContext.jsx';
import { scoreColor, SEVERITY_STYLE, timeAgo } from '../lib/format.js';
import { Icon } from '../components/Icon.jsx';
import { ProviderMark, STATUS_LABEL, StatusDot } from '../components/primitives.jsx';
import { ScoreGauge, useAnimatedNumber } from '../components/ScoreGauge.jsx';
import { Sparkline } from '../components/Sparkline.jsx';
import { RecommendationsFeed } from '../components/Recommendations.jsx';

function ScoreCard({ risk }) {
  const delta = risk.trend.delta7d;
  const color = scoreColor(risk.score);
  return (
    <section className="card relative overflow-hidden lg:col-span-5">
      <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full blur-3xl" style={{ background: `${color}18` }} />
      <div className="card-header">
        <div>
          <p className="eyebrow">Overall security score</p>
          <p className="mt-0.5 text-xs text-slate-500">Weighted by severity and exposure of open findings</p>
        </div>
        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ${delta >= 0 ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'}`}>
          <Icon name={delta >= 0 ? 'trendUp' : 'trendDown'} className="h-3.5 w-3.5" />
          {delta >= 0 ? '+' : ''}{delta} vs 7d
        </span>
      </div>
      <div className="flex flex-col items-center gap-6 px-5 pb-5 pt-4 sm:flex-row sm:items-center">
        <ScoreGauge score={risk.score} grade={risk.grade} label={risk.label} size={210} />
        <div className="w-full flex-1 space-y-4">
          <div>
            <div className="flex items-baseline justify-between">
              <p className="eyebrow">30-day trend</p>
              <p className="text-[11px] text-slate-500">{risk.trend.points.length} snapshots</p>
            </div>
            <Sparkline points={risk.trend.points} color={color} />
          </div>
          <div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="eyebrow">Coverage</span>
              <span className="tabular text-slate-400">{risk.coverage.monitored}/{risk.coverage.total} sources</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
              <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-indigo-500 transition-all duration-700" style={{ width: `${risk.coverage.percent}%` }} />
            </div>
            {risk.coverage.monitored < risk.coverage.total && (
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                Connect the remaining sources so the score reflects your whole estate.
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value, tone = 'text-white', icon, iconClass, children }) {
  const animated = useAnimatedNumber(value, 700);
  return (
    <div className="card flex flex-col justify-between p-5">
      <div className="flex items-start justify-between">
        <p className="eyebrow">{label}</p>
        <span className={`rounded-lg p-2 ${iconClass}`}><Icon name={icon} className="h-4 w-4" /></span>
      </div>
      <p className={`tabular mt-3 font-mono text-4xl font-semibold tracking-tight ${tone}`}>{animated}</p>
      <div className="mt-2 text-xs text-slate-500">{children}</div>
    </div>
  );
}

function MetricsColumn({ risk, integrations, activity }) {
  const active = integrations.filter((i) => i.monitored).length;
  return (
    <div className="grid gap-4 sm:grid-cols-3 lg:col-span-7">
      <Metric label="Critical vulnerabilities" value={risk.counts.critical} tone="text-rose-400" icon="alert" iconClass="bg-rose-500/10 text-rose-400">
        <span className="text-orange-300">{risk.counts.high} high</span> · <span className="text-amber-200">{risk.counts.medium} medium</span> · {risk.counts.low} low
      </Metric>
      <Metric label="Open findings" value={risk.open} icon="layers" iconClass="bg-brand-500/10 text-brand-300">
        {activity.remediating > 0
          ? <span className="text-brand-300">{activity.remediating} remediation{activity.remediating === 1 ? '' : 's'} running</span>
          : <span className="text-emerald-300/80">{activity.resolved} resolved</span>}
      </Metric>
      <Metric label="Active integrations" value={active} icon="plug" iconClass="bg-indigo-500/10 text-indigo-300">
        <div className="flex items-center gap-1.5">
          {integrations.map((i) => (
            <span key={i.id} title={`${i.name}: ${STATUS_LABEL[i.status]}`} className={`h-1.5 flex-1 rounded-full ${i.monitored ? 'bg-emerald-400/80' : i.connected ? 'bg-amber-400/70' : 'bg-white/10'}`} />
          ))}
        </div>
        <p className="mt-1.5">of {integrations.length} supported sources</p>
      </Metric>

      <section className="card sm:col-span-3">
        <div className="card-header">
          <p className="eyebrow">Risk concentration by category</p>
          <p className="text-[11px] text-slate-500">Share of total risk</p>
        </div>
        <div className="grid gap-x-8 gap-y-3 p-5 sm:grid-cols-2">
          {risk.byCategory.length === 0 && <p className="text-sm text-slate-500">No open risk.</p>}
          {risk.byCategory.slice(0, 8).map((c) => (
            <div key={c.category}>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-300">{c.category}</span>
                <span className="tabular text-slate-500">{c.open} open · <span className="text-slate-300">{c.share}%</span></span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.05]">
                <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-brand-400 transition-all duration-700" style={{ width: `${Math.max(c.share, 2)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function IntegrationStatusCards({ integrations, risk, onManage }) {
  const scores = Object.fromEntries(risk.byIntegration.map((i) => [i.id, i]));
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Integrations</h2>
          <p className="text-xs text-slate-500">Live status of connected sources</p>
        </div>
        <button type="button" onClick={onManage} className="btn-ghost text-xs">Manage <Icon name="chevronRight" className="h-3.5 w-3.5" /></button>
      </div>
      <ul className="divide-y divide-white/[0.05]">
        {integrations.map((i) => {
          const scoped = scores[i.id];
          return (
            <li key={i.id} className="flex items-center gap-3 px-5 py-3">
              <ProviderMark integration={i} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-200">{i.name}</p>
                <p className="flex items-center gap-1.5 text-xs text-slate-500">
                  <StatusDot status={i.status} />
                  {STATUS_LABEL[i.status]}
                  {i.lastSyncAt && i.connected && <span className="truncate">· {timeAgo(i.lastSyncAt)}</span>}
                </p>
              </div>
              {i.monitored && scoped ? (
                <div className="text-right">
                  <p className="tabular font-mono text-sm font-semibold" style={{ color: scoreColor(scoped.score) }}>{scoped.score}</p>
                  <p className="text-[11px] text-slate-500">
                    {i.findings.counts.critical > 0
                      ? <span className={SEVERITY_STYLE.critical.text}>{i.findings.counts.critical} critical</span>
                      : `${i.findings.open} open`}
                  </p>
                </div>
              ) : (
                <button type="button" onClick={onManage} className="btn-secondary px-2.5 py-1 text-xs">{i.connected ? 'Resume' : 'Connect'}</button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ComplianceCard({ frameworks }) {
  if (!frameworks?.length) return null;
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Compliance readiness</h2>
          <p className="text-xs text-slate-500">Controls assessed on monitored platforms</p>
        </div>
        <Icon name="shieldCheck" className="h-4 w-4 text-slate-500" />
      </div>
      <div className="space-y-4 p-5">
        {frameworks.map((fw) => {
          const color = fw.readiness == null ? '#475569' : scoreColor(fw.readiness);
          return (
            <div key={fw.id}>
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium text-slate-200">{fw.name}</span>
                <span className="tabular font-mono text-lg font-semibold" style={{ color }}>{fw.readiness == null ? 'n/a' : `${fw.readiness}%`}</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                <div className="h-full rounded-full transition-all duration-700" style={{ width: `${fw.readiness ?? 0}%`, background: color }} />
              </div>
              <p className="mt-1.5 text-[11px] text-slate-500">
                {fw.passing} passing · {fw.partial} partial · {fw.failing} failing of {fw.assessed} controls
                {fw.topGaps?.[0] && <> · top gap <span className="font-mono text-slate-400">{fw.topGaps[0].id}</span></>}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function Overview({ navigate }) {
  const { data } = useVeyra();
  const { risk, integrations, recommendations, activity } = data;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-12">
        <ScoreCard risk={risk} />
        <MetricsColumn risk={risk} integrations={integrations} activity={activity} />
      </div>
      <div className="grid gap-6 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <RecommendationsFeed recommendations={recommendations} integrations={integrations} limit={5} onViewAll={() => navigate('recommendations')} />
        </div>
        <div className="space-y-6 xl:col-span-4">
          <IntegrationStatusCards integrations={integrations} risk={risk} onManage={() => navigate('integrations')} />
          <ComplianceCard frameworks={data.compliance} />
        </div>
      </div>
    </div>
  );
}
