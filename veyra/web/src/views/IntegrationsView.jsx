import { useState } from 'react';
import { useVeyra } from '../lib/VeyraContext.jsx';
import { SEVERITIES, SEVERITY_STYLE, timeAgo } from '../lib/format.js';
import { ConnectModal } from '../components/ConnectModal.jsx';
import { Icon, Spinner } from '../components/Icon.jsx';
import { ProviderMark, STATUS_LABEL, StatusDot, Toggle } from '../components/primitives.jsx';

function IntegrationCard({ integration: i, onConnect }) {
  const { actions, busy } = useVeyra();
  const working = Boolean(busy[`integration:${i.id}`]) || i.status === 'syncing' || i.status === 'connecting';
  const toggling = Boolean(busy[`toggle:${i.id}`]);

  return (
    <article className={`card flex flex-col transition ${i.monitored ? 'hover:border-white/[0.12]' : ''}`}>
      <div className="flex items-start gap-4 p-5">
        <ProviderMark integration={i} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-100">{i.name}</h3>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-400">
                <StatusDot status={i.status} /> {STATUS_LABEL[i.status]}
                {i.account && <span className="truncate text-slate-500">· {i.account.label}</span>}
              </p>
            </div>
            <Toggle
              checked={i.enabled}
              disabled={!i.connected || toggling || working}
              onChange={(enabled) => actions.setEnabled(i, enabled)}
              label={`${i.enabled ? 'Pause' : 'Resume'} monitoring for ${i.name}`}
            />
          </div>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">{i.description}</p>
        </div>
      </div>

      {i.connected ? (
        <div className="mx-5 grid grid-cols-4 gap-2 rounded-xl border border-white/[0.05] bg-ink-950/50 p-3">
          {SEVERITIES.map((s) => (
            <div key={s} className="text-center">
              <p className={`tabular font-mono text-lg font-semibold ${i.findings.counts[s] ? SEVERITY_STYLE[s].text : 'text-slate-600'}`}>{i.findings.counts[s]}</p>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">{SEVERITY_STYLE[s].label}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="mx-5 rounded-xl border border-dashed border-white/10 p-3 text-xs text-slate-500">
          <span className="font-medium text-slate-400">{i.checks} security checks</span> ready to run · {i.authMethod}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 px-5 pb-5 pt-4">
        <p className="text-[11px] text-slate-500">
          {i.connected ? <>Last scan {timeAgo(i.lastSyncAt)} · {i.scans} scan{i.scans === 1 ? '' : 's'}</> : 'Read-only · revocable any time'}
        </p>
        <div className="flex gap-2">
          {i.connected ? (
            <>
              <button type="button" className="btn-secondary px-3 py-1.5 text-xs" disabled={working || !i.enabled} onClick={() => actions.sync(i)}>
                {working ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="refresh" className="h-3.5 w-3.5" />} {working ? 'Scanning' : 'Scan now'}
              </button>
              <button type="button" className="btn-danger px-3 py-1.5 text-xs" disabled={working} onClick={() => actions.disconnect(i)}>
                <Icon name="unlink" className="h-3.5 w-3.5" /> Disconnect
              </button>
            </>
          ) : (
            <button type="button" className="btn-primary px-3 py-1.5 text-xs" disabled={working} onClick={() => onConnect(i)}>
              <Icon name="link" className="h-3.5 w-3.5" /> Connect
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export function IntegrationsView() {
  const { data } = useVeyra();
  const [connecting, setConnecting] = useState(null);
  const connected = data.integrations.filter((i) => i.connected).length;

  return (
    <div className="space-y-6">
      <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="eyebrow">Integration management</p>
          <p className="mt-1 text-sm text-slate-400">
            <span className="font-semibold text-slate-200">{connected} of {data.integrations.length}</span> sources connected.
            Pausing monitoring keeps the connection but removes its findings from the score.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Icon name="lock" className="h-4 w-4 text-emerald-400" /> All connectors use read-only scopes
        </div>
      </div>

      <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
        {data.integrations.map((i) => <IntegrationCard key={i.id} integration={i} onConnect={setConnecting} />)}
      </div>

      {connecting && <ConnectModal integration={connecting} onClose={() => setConnecting(null)} />}
    </div>
  );
}
