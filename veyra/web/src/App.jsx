import { useCallback, useEffect, useState } from 'react';
import { useVeyra } from './lib/VeyraContext.jsx';
import { scoreColor, timeAgo } from './lib/format.js';
import { Icon, Spinner } from './components/Icon.jsx';
import { Skeleton } from './components/primitives.jsx';
import { ScoreChangeChip, useAnimatedNumber, useScoreChange } from './components/ScoreGauge.jsx';
import { Overview } from './views/Overview.jsx';
import { RecommendationsView } from './views/RecommendationsView.jsx';
import { FindingsView } from './views/FindingsView.jsx';
import { IntegrationsView } from './views/IntegrationsView.jsx';

const ROUTES = {
  overview: { label: 'Overview', icon: 'gauge', title: 'Security posture', subtitle: 'Unified risk across your cloud, identity and collaboration stack', view: Overview },
  recommendations: { label: 'Recommendations', icon: 'sparkles', title: 'Security Brain Recommendations', subtitle: 'What to fix first, and why it matters', view: RecommendationsView },
  findings: { label: 'Findings', icon: 'list', title: 'Findings', subtitle: 'Every issue detected across connected integrations', view: FindingsView },
  integrations: { label: 'Integrations', icon: 'plug', title: 'Integrations', subtitle: 'Connect, pause and rescan your security data sources', view: IntegrationsView },
};

function useHashRoute() {
  const read = () => {
    const key = window.location.hash.replace(/^#\/?/, '');
    return ROUTES[key] ? key : 'overview';
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const navigate = useCallback((key) => {
    window.location.hash = `/${key}`;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);
  return [route, navigate];
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/veyra.svg" alt="" className="h-8 w-8" />
      <div className="leading-tight">
        <p className="text-[15px] font-semibold tracking-tight text-white">Veyra</p>
        <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-brand-300/80">Security Brain</p>
      </div>
    </div>
  );
}

function NavLinks({ route, navigate, data, compact = false }) {
  const badge = {
    recommendations: data?.recommendations.length,
    integrations: data ? `${data.integrations.filter((i) => i.monitored).length}/${data.integrations.length}` : null,
  };
  return Object.entries(ROUTES).map(([key, r]) => {
    const active = key === route;
    return (
      <a
        key={key}
        href={`#/${key}`}
        onClick={(e) => { e.preventDefault(); navigate(key); }}
        aria-current={active ? 'page' : undefined}
        className={`group flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
          active ? 'bg-white/[0.06] text-white shadow-[inset_2px_0_0_0_#38d5f0]' : 'text-slate-400 hover:bg-white/[0.03] hover:text-slate-200'
        }`}
      >
        <Icon name={r.icon} className={`h-4 w-4 ${active ? 'text-brand-300' : 'text-slate-500 group-hover:text-slate-300'}`} />
        {r.label}
        {!compact && badge[key] != null && <span className="tabular ml-auto rounded-md bg-white/[0.05] px-1.5 py-0.5 text-[10px] text-slate-400">{badge[key]}</span>}
      </a>
    );
  });
}

function Sidebar({ route, navigate }) {
  const { data, actions, busy } = useVeyra();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-white/[0.06] bg-ink-950/80 backdrop-blur-xl lg:flex">
      <div className="px-5 pb-6 pt-6"><Logo /></div>
      <nav className="flex flex-col gap-1 px-3"><NavLinks route={route} navigate={navigate} data={data} /></nav>
      <div className="mt-auto space-y-3 p-4">
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
          <p className="eyebrow">Tenant</p>
          <p className="mt-1 text-sm font-medium text-slate-200">Acme Corp</p>
          <p className="text-[11px] text-slate-500">Demo environment · simulated data</p>
          <button type="button" onClick={actions.reset} disabled={busy.reset} className="btn-ghost mt-2 w-full justify-start px-2 py-1.5 text-xs">
            {busy.reset ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="rotate" className="h-3.5 w-3.5" />} Reset demo data
          </button>
        </div>
      </div>
    </aside>
  );
}

/** Live score in the header, so Auto-Fix results are visible from every page. */
function ScorePill({ risk, onClick }) {
  const animated = useAnimatedNumber(risk.score);
  const change = useScoreChange(risk.score);
  const color = scoreColor(animated);
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 transition hover:bg-white/[0.04] ${change?.delta > 0 ? 'animate-glow-pulse' : ''}`}
      style={{ borderColor: `${color}55` }}
      aria-label={`Security score ${risk.score}, grade ${risk.grade}`}
      title="Overall security score"
    >
      <span className="tabular font-mono text-base font-semibold leading-none" style={{ color }}>{animated}</span>
      <span className="text-[11px] font-semibold text-slate-400">{risk.grade}</span>
      <ScoreChangeChip change={change} className="absolute -top-3 left-1/2 -translate-x-1/2" />
    </button>
  );
}

function Header({ route, navigate }) {
  const { data, actions, busy } = useVeyra();
  const meta = ROUTES[route];
  const lastScan = data?.integrations
    .map((i) => i.lastSyncAt)
    .filter(Boolean)
    .sort()
    .at(-1);

  return (
    <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-ink-950/75 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-4 px-4 py-3 lg:hidden">
        <Logo />
      </div>
      <nav className="scrollbar-thin flex gap-1 overflow-x-auto px-3 pb-2 lg:hidden"><NavLinks route={route} navigate={navigate} data={data} compact /></nav>
      <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between lg:px-8 lg:py-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-white">{meta.title}</h1>
          <p className="mt-0.5 text-sm text-slate-500">{meta.subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          {data && <ScorePill risk={data.risk} onClick={() => navigate('overview')} />}
          {lastScan && (
            <span className="hidden items-center gap-1.5 text-xs text-slate-500 md:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> Last scan {timeAgo(lastScan)}
            </span>
          )}
          <button type="button" onClick={actions.syncAll} disabled={busy.syncAll || !data} className="btn-secondary">
            {busy.syncAll ? <Spinner /> : <Icon name="refresh" />} {busy.syncAll ? 'Scanning…' : 'Rescan all'}
          </button>
          <button
            type="button"
            onClick={actions.downloadReport}
            disabled={busy.report || !data}
            className="btn-primary"
            aria-label="Download Executive Report (PDF)"
            title="Executive summary, platform breakdown, top 5 CISO actions and SOC 2 / ISO 27001 readiness"
          >
            {busy.report ? <Spinner /> : <Icon name="download" />}
            <span className="hidden xl:inline">{busy.report ? 'Generating…' : 'Download Executive Report (PDF)'}</span>
            <span className="xl:hidden">{busy.report ? 'Generating…' : 'Report (PDF)'}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function LoadingState() {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-12">
        <Skeleton className="h-72 lg:col-span-5" />
        <div className="grid gap-4 sm:grid-cols-3 lg:col-span-7">
          <Skeleton className="h-36" /><Skeleton className="h-36" /><Skeleton className="h-36" />
          <Skeleton className="h-32 sm:col-span-3" />
        </div>
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}

function ErrorState({ error, onRetry }) {
  return (
    <div className="card mx-auto mt-10 max-w-lg p-8 text-center">
      <div className="mx-auto mb-4 w-fit rounded-2xl bg-rose-500/10 p-3 text-rose-400"><Icon name="alert" className="h-6 w-6" /></div>
      <h2 className="font-semibold text-slate-100">Cannot load the dashboard</h2>
      <p className="mt-2 text-sm text-slate-400">{error.message}</p>
      <p className="mt-1 text-xs text-slate-500">Start the API with <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono">npm run dev</code> from the <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono">veyra/</code> folder.</p>
      <button type="button" onClick={onRetry} className="btn-primary mt-5"><Icon name="refresh" /> Retry</button>
    </div>
  );
}

export default function App() {
  const [route, navigate] = useHashRoute();
  const { data, error, actions } = useVeyra();
  const View = ROUTES[route].view;

  useEffect(() => {
    document.title = `${ROUTES[route].label} · Veyra Security Brain`;
  }, [route]);

  return (
    <div className="min-h-screen">
      <Sidebar route={route} navigate={navigate} />
      <div className="lg:pl-64">
        <Header route={route} navigate={navigate} />
        <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-8 lg:py-8">
          {data ? <View navigate={navigate} /> : error ? <ErrorState error={error} onRetry={actions.refresh} /> : <LoadingState />}
        </main>
      </div>
    </div>
  );
}
