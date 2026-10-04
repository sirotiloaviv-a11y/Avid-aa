import { createRng } from './lib/rng.js';
import { badRequest, conflict, HttpError, notFound } from './lib/errors.js';
import { computeRiskScore, countBySeverity, findingPenalty, projectedGain, scoreFromPenalty, SEVERITIES } from './engine/risk.js';
import { buildRecommendations } from './engine/prioritize.js';
import { computeCompliance } from './engine/compliance.js';
import { getPlaybook } from './remediation/playbooks.js';
import { BASELINE_CHECKS } from './connectors/baselineChecks.js';

const DAY_MS = 24 * 60 * 60 * 1000;
const HISTORY_LIMIT = 500;
const FINDING_STATUSES = ['open', 'remediating', 'resolved'];

/**
 * The Security Brain: owns integration state and findings, and derives the
 * risk score and recommendations from them. State is in memory; a restart or
 * POST /api/demo/reset returns the prototype to its seeded demo state.
 */
export class SecurityBrain {
  constructor({ connectors, demoConnections = {}, remediationDelayMs = 2500, now = () => Date.now(), tenantName = 'Acme Corp' }) {
    this.connectors = connectors;
    this.tenantName = tenantName;
    this.demoConnections = demoConnections;
    this.remediationDelayMs = remediationDelayMs;
    this.now = now;
    this.timers = new Set();
    this.syncs = new Map();
    this.#clear();
  }

  #clear() {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
    this.syncs.clear();
    this.findings = new Map();
    this.history = [];
    this.integrations = new Map(
      [...this.connectors.keys()].map((id) => [id, {
        id, connected: false, enabled: false, status: 'disconnected',
        account: null, connectedAt: null, lastSyncAt: null, scanCount: 0, error: null,
      }]),
    );
  }

  /** Connect the demo accounts and backfill a month of score history. */
  async init() {
    for (const [id, credentials] of Object.entries(this.demoConnections)) {
      if (this.connectors.has(id)) await this.connect(id, credentials, { record: false, instant: true });
    }
    this.#backfillHistory();
    return this;
  }

  async reset() {
    this.#clear();
    return this.init();
  }

  close() {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
  }

  // ---------------------------------------------------------------- integrations

  #connector(id) {
    const connector = this.connectors.get(id);
    if (!connector) throw notFound(`Integration "${id}"`);
    return connector;
  }

  #state(id) {
    this.#connector(id);
    return this.integrations.get(id);
  }

  #isMonitored(state) {
    return state.connected && state.enabled;
  }

  #integrationView(id) {
    const connector = this.connectors.get(id);
    const state = this.integrations.get(id);
    const providerFindings = [...this.findings.values()].filter((f) => f.provider === id);
    const open = providerFindings.filter((f) => f.status !== 'resolved');
    return {
      ...connector.describe(),
      connected: state.connected,
      enabled: state.enabled,
      monitored: this.#isMonitored(state),
      status: state.status,
      error: state.error,
      account: state.account ? { label: state.account.label } : null,
      connectedAt: state.connectedAt,
      lastSyncAt: state.lastSyncAt,
      scans: state.scanCount,
      findings: { open: open.length, resolved: providerFindings.length - open.length, counts: countBySeverity(open) },
    };
  }

  listIntegrations() {
    return [...this.connectors.keys()].map((id) => this.#integrationView(id));
  }

  getIntegration(id) {
    this.#state(id);
    return this.#integrationView(id);
  }

  async connect(id, credentials, { record = true, instant = false } = {}) {
    const connector = this.#connector(id);
    const state = this.integrations.get(id);
    if (state.status === 'connecting' || state.status === 'syncing') {
      throw conflict(`${connector.name} is busy, try again in a moment`);
    }

    const previous = { ...state };
    state.status = 'connecting';
    state.error = null;
    let account;
    try {
      account = await connector.authenticate(credentials, { simulateLatency: !instant });
    } catch (error) {
      Object.assign(state, previous);
      if (error.status === 400) throw badRequest(error.message, { fields: error.fields });
      throw error;
    }

    // Reconnecting to a different account must not leave the old account's findings behind.
    if (state.account && state.account.key !== account.key) this.#dropFindings(id);

    Object.assign(state, {
      connected: true, enabled: true, status: 'connected', account,
      connectedAt: new Date(this.now()).toISOString(), scanCount: 0, error: null,
    });
    await this.sync(id, { record, instant });
    return this.#integrationView(id);
  }

  disconnect(id) {
    const state = this.#state(id);
    if (!state.connected) throw conflict(`${this.connectors.get(id).name} is not connected`);
    this.#dropFindings(id);
    Object.assign(state, {
      connected: false, enabled: false, status: 'disconnected', account: null,
      connectedAt: null, lastSyncAt: null, scanCount: 0, error: null,
    });
    this.#recordScore();
    return this.#integrationView(id);
  }

  setEnabled(id, enabled) {
    if (typeof enabled !== 'boolean') throw badRequest('"enabled" must be a boolean');
    const state = this.#state(id);
    if (!state.connected) throw conflict(`Connect ${this.connectors.get(id).name} before changing monitoring`);
    if (state.enabled !== enabled) {
      state.enabled = enabled;
      state.status = enabled ? 'connected' : 'paused';
      this.#recordScore();
    }
    return this.#integrationView(id);
  }

  /** Concurrent sync requests for the same integration share one scan. */
  sync(id, options) {
    const state = this.#state(id);
    if (!state.connected) return Promise.reject(conflict(`${this.connectors.get(id).name} is not connected`));
    if (this.syncs.has(id)) return this.syncs.get(id);
    const run = this.#runSync(id, options).finally(() => this.syncs.delete(id));
    this.syncs.set(id, run);
    return run;
  }

  async #runSync(id, { record = true, instant = false } = {}) {
    const connector = this.connectors.get(id);
    const state = this.integrations.get(id);
    const account = state.account;
    state.status = 'syncing';
    try {
      const scanned = await connector.collect(account, { scanNumber: state.scanCount, now: this.now(), simulateLatency: !instant });
      // The integration may have been disconnected or re-pointed while the scan ran.
      if (state.account !== account) return this.#integrationView(id);
      this.#merge(id, scanned);
      state.scanCount += 1;
      state.lastSyncAt = new Date(this.now()).toISOString();
      state.status = state.enabled ? 'connected' : 'paused';
      state.error = null;
    } catch (error) {
      state.status = 'error';
      state.error = error.message;
      throw new HttpError(502, `Scan of ${connector.name} failed: ${error.message}`);
    }
    if (record) this.#recordScore();
    return this.#integrationView(id);
  }

  async syncAll() {
    const ids = [...this.integrations.values()].filter((s) => this.#isMonitored(s)).map((s) => s.id);
    await Promise.all(ids.map((id) => this.sync(id, { record: false })));
    this.#recordScore();
    return this.listIntegrations();
  }

  /**
   * Fold a scan into the finding store. A finding we already know keeps its
   * workflow status; a resolved one stays resolved (in this simulation a
   * remediation really fixes the issue); an open one that the scan no longer
   * reports is closed as no longer detected.
   */
  #merge(provider, scanned) {
    const seen = new Set();
    const nowIso = new Date(this.now()).toISOString();
    for (const finding of scanned) {
      seen.add(finding.id);
      const existing = this.findings.get(finding.id);
      if (!existing) {
        this.findings.set(finding.id, { ...finding, lastSeenAt: nowIso });
      } else if (existing.status !== 'resolved') {
        const { status, remediationStartedAt, autoFixJobId } = existing;
        this.findings.set(finding.id, { ...finding, status, remediationStartedAt, autoFixJobId, lastSeenAt: nowIso });
      }
    }
    for (const finding of this.findings.values()) {
      if (finding.provider === provider && finding.status === 'open' && !seen.has(finding.id)) {
        Object.assign(finding, { status: 'resolved', resolvedAt: nowIso, resolution: 'no-longer-detected' });
      }
    }
  }

  #dropFindings(provider) {
    for (const [id, finding] of this.findings) {
      if (finding.provider === provider) this.findings.delete(id);
    }
  }

  // -------------------------------------------------------------------- findings

  #openFindings() {
    return [...this.findings.values()].filter((f) => f.status !== 'resolved' && this.#isMonitored(this.integrations.get(f.provider)));
  }

  #playbookFor(finding) {
    return getPlaybook(finding, this.integrations.get(finding.provider)?.account);
  }

  #findingView(finding) {
    const connector = this.connectors.get(finding.provider);
    const { autoFixJobId, ...rest } = finding;
    return {
      ...rest,
      autoFix: this.#playbookFor(finding).autoFix,
      monitored: this.#isMonitored(this.integrations.get(finding.provider)),
      integration: { id: connector.id, name: connector.name, shortName: connector.definition.shortName, color: connector.definition.color },
    };
  }

  listFindings({ provider, severity, status, q } = {}) {
    if (provider) this.#connector(provider);
    if (severity && !SEVERITIES.includes(severity)) throw badRequest(`severity must be one of ${SEVERITIES.join(', ')}`);
    if (status && !FINDING_STATUSES.includes(status)) throw badRequest(`status must be one of ${FINDING_STATUSES.join(', ')}`);
    const needle = typeof q === 'string' ? q.trim().toLowerCase() : '';

    return [...this.findings.values()]
      .filter((f) => (!provider || f.provider === provider)
        && (!severity || f.severity === severity)
        && (!status || f.status === status)
        && (!needle || `${f.title} ${f.resource.name} ${f.category}`.toLowerCase().includes(needle)))
      .sort((a, b) => SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity) || b.detectedAt.localeCompare(a.detectedAt))
      .map((f) => this.#findingView(f));
  }

  getFinding(id) {
    const finding = this.findings.get(id);
    if (!finding) throw notFound('Finding');
    return this.#findingView(finding);
  }

  /**
   * Start the provider's remediation playbook. In the prototype the playbook
   * is simulated: the finding moves to "remediating" and resolves after
   * `remediationDelayMs`, at which point the score is recomputed.
   */
  #remediable(id) {
    const finding = this.findings.get(id);
    if (!finding) throw notFound('Finding');
    if (!this.#isMonitored(this.integrations.get(finding.provider))) {
      throw conflict('Resume monitoring for this integration before remediating its findings');
    }
    if (finding.status === 'remediating') throw conflict('Remediation is already in progress');
    if (finding.status === 'resolved') throw conflict('Finding is already resolved');
    return finding;
  }

  remediate(id) {
    const finding = this.#remediable(id);

    finding.status = 'remediating';
    finding.remediationStartedAt = new Date(this.now()).toISOString();

    const timer = setTimeout(() => {
      this.timers.delete(timer);
      const current = this.findings.get(id);
      if (current?.status !== 'remediating') return;
      Object.assign(current, { status: 'resolved', resolvedAt: new Date(this.now()).toISOString(), resolution: 'remediated' });
      this.#recordScore();
    }, this.remediationDelayMs);
    timer.unref?.();
    this.timers.add(timer);

    return this.#findingView(finding);
  }

  // ------------------------------------------------------------ auto-fix hooks
  //
  // The AutoFixEngine drives the workflow; these methods are the only way it
  // touches state. A claim is identified by the job id, so a job that outlives
  // a reset, disconnect or manual change can never resolve the wrong finding.

  claimAutoFix(id, jobId) {
    const finding = this.#remediable(id);
    const playbook = this.#playbookFor(finding);
    if (!playbook.autoFix.supported) {
      throw new HttpError(422, `Auto-Fix is not available for this finding: ${playbook.autoFix.reason}`);
    }
    Object.assign(finding, { status: 'remediating', remediationStartedAt: new Date(this.now()).toISOString(), autoFixJobId: jobId });
    return this.#autoFixContext(finding, playbook);
  }

  /** Re-validates a claim mid-flight; returns a reason string when it is no longer valid. */
  autoFixBlocker(id, jobId) {
    const finding = this.findings.get(id);
    if (!finding || finding.autoFixJobId !== jobId || finding.status !== 'remediating') {
      return 'The finding changed while the fix was running (rescan, reset or manual action).';
    }
    const state = this.integrations.get(finding.provider);
    if (!state.connected) return `${this.connectors.get(finding.provider).name} was disconnected.`;
    if (!state.enabled) return `Monitoring for ${this.connectors.get(finding.provider).name} was paused.`;
    return null;
  }

  completeAutoFix(id, jobId) {
    if (this.autoFixBlocker(id, jobId)) return false;
    const finding = this.findings.get(id);
    Object.assign(finding, { status: 'resolved', resolvedAt: new Date(this.now()).toISOString(), resolution: 'auto-fixed', autoFixJobId: undefined });
    this.#recordScore();
    return true;
  }

  releaseAutoFix(id, jobId) {
    const finding = this.findings.get(id);
    if (finding?.autoFixJobId === jobId && finding.status === 'remediating') {
      Object.assign(finding, { status: 'open', remediationStartedAt: undefined, autoFixJobId: undefined });
    }
  }

  #autoFixContext(finding, playbook = this.#playbookFor(finding)) {
    const connector = this.connectors.get(finding.provider);
    const open = this.#openFindings();
    const isOpen = open.some((f) => f.id === finding.id);
    return {
      finding: this.#findingView(finding),
      account: this.integrations.get(finding.provider)?.account ?? null,
      integration: { id: connector.id, name: connector.name, vendor: connector.definition.vendor },
      playbook,
      score: this.#currentRisk().score,
      projectedGain: isOpen ? projectedGain(finding, open) : 0,
    };
  }

  /** Everything the AI service needs to reason about one finding. */
  findingContext(id) {
    const finding = this.findings.get(id);
    if (!finding) throw notFound('Finding');
    return this.#autoFixContext(finding);
  }

  /** Resolves once every in-flight remediation has finished (used by tests). */
  async settle() {
    while (this.timers.size) await new Promise((resolve) => setTimeout(resolve, Math.max(5, this.remediationDelayMs)));
  }

  // --------------------------------------------------------------- risk & advice

  #monitoredIntegrations() {
    return [...this.integrations.values()]
      .filter((s) => this.#isMonitored(s))
      .map((s) => ({ id: s.id, name: this.connectors.get(s.id).name }));
  }

  #currentRisk() {
    return computeRiskScore(this.#openFindings(), this.#monitoredIntegrations(), this.connectors.size);
  }

  #recordScore() {
    const { score } = this.#currentRisk();
    this.history.push({ t: new Date(this.now()).toISOString(), score });
    if (this.history.length > HISTORY_LIMIT) this.history.splice(0, this.history.length - HISTORY_LIMIT);
  }

  /** Thirty daily points of plausible history ending at today's score. */
  #backfillHistory() {
    const { score } = this.#currentRisk();
    const rng = createRng('veyra:history');
    const today = this.now();
    const points = [{ t: new Date(today).toISOString(), score }];
    let value = score;
    for (let day = 1; day <= 30; day++) {
      value = Math.min(97, Math.max(5, value + rng.int(-2, 3)));
      points.unshift({ t: new Date(today - day * DAY_MS).toISOString(), score: value });
    }
    this.history = points;
  }

  riskScore() {
    const risk = this.#currentRisk();
    const now = this.now();
    const weekAgo = now - 7 * DAY_MS;
    const baseline = [...this.history].reverse().find((p) => Date.parse(p.t) <= weekAgo) ?? this.history[0];
    return {
      ...risk,
      trend: {
        delta7d: baseline ? risk.score - baseline.score : 0,
        points: this.history.slice(-60),
      },
      calculatedAt: new Date(now).toISOString(),
    };
  }

  recommendations({ limit } = {}) {
    const integrationsById = new Map([...this.connectors.values()].map((c) => [c.id, { id: c.id, ...c.definition }]));
    return buildRecommendations(this.#openFindings(), integrationsById, { limit, now: this.now() })
      .map((rec) => ({ ...rec, autoFix: this.#playbookFor(this.findings.get(rec.findingId)).autoFix }));
  }

  compliance() {
    const assessedChecks = [...this.integrations.values()]
      .filter((s) => this.#isMonitored(s))
      .flatMap((s) => [...this.connectors.get(s.id).templates, ...(BASELINE_CHECKS[s.id] ?? [])]
        .map((check) => ({ provider: s.id, key: check.key, category: check.category, frameworks: check.frameworks })));
    return computeCompliance(assessedChecks, this.#openFindings());
  }

  /** Data model behind the executive PDF report. */
  executiveReport({ topN = 5 } = {}) {
    const risk = this.riskScore();
    const open = this.#openFindings();
    const top = this.recommendations({ limit: topN });
    const topIds = new Set(top.map((r) => r.findingId));
    const remainingPenalty = open.filter((f) => !topIds.has(f.id)).reduce((sum, f) => sum + findingPenalty(f), 0);
    const scores = new Map(risk.byIntegration.map((i) => [i.id, i]));

    return {
      generatedAt: new Date(this.now()).toISOString(),
      tenant: this.tenantName,
      risk,
      projectedScore: scoreFromPenalty(remainingPenalty),
      integrations: this.listIntegrations().map((i) => ({
        id: i.id,
        name: i.name,
        shortName: i.shortName,
        color: i.color,
        status: i.status,
        monitored: i.monitored,
        account: i.account?.label ?? null,
        score: scores.get(i.id)?.score ?? null,
        grade: scores.get(i.id)?.grade ?? null,
        counts: i.findings.counts,
        open: i.findings.open,
        lastSyncAt: i.lastSyncAt,
      })),
      topActions: top,
      compliance: this.compliance(),
    };
  }

  dashboard() {
    const all = [...this.findings.values()];
    return {
      generatedAt: new Date(this.now()).toISOString(),
      risk: this.riskScore(),
      integrations: this.listIntegrations(),
      recommendations: this.recommendations(),
      compliance: this.compliance().map(({ controls, ...summary }) => summary),
      activity: {
        remediating: all.filter((f) => f.status === 'remediating').length,
        resolved: all.filter((f) => f.status === 'resolved').length,
      },
    };
  }
}
