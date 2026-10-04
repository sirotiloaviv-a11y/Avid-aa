import { randomUUID } from 'node:crypto';
import { HttpError, notFound } from '../lib/errors.js';

const sleep = (ms) => new Promise((resolve) => {
  const timer = setTimeout(resolve, ms);
  timer.unref?.();
});

const STEPS = [
  { key: 'validate', label: 'Validate permissions' },
  { key: 'snapshot', label: 'Capture rollback snapshot' },
  { key: 'execute', label: 'Execute fix' },
  { key: 'verify', label: 'Verify & resolve finding' },
  { key: 'rescore', label: 'Recalculate risk score' },
];

const JOB_LIMIT = 100;

/**
 * Auto-Fix engine: runs a remediation playbook as a sequence of observable
 * steps. Jobs are asynchronous; clients start one with `start()` and poll
 * `get()` for step-by-step progress.
 *
 * Execution is simulated (each step waits `stepMs`), but the state changes are
 * real: the finding is claimed at the start, re-validated before each step,
 * resolved at the end, and released back to "open" if anything fails.
 */
export class AutoFixEngine {
  constructor({ brain, stepMs = 700, now = () => Date.now(), logger = console }) {
    this.brain = brain;
    this.stepMs = stepMs;
    this.now = now;
    this.logger = logger;
    this.jobs = new Map();
    this.running = new Map();
  }

  /** Validates synchronously (404/409/422 surface to the caller), then runs in the background. */
  start(findingId) {
    if (typeof findingId !== 'string' || !findingId.trim()) {
      throw new HttpError(400, '"findingId" is required');
    }
    const id = `fix_${randomUUID().slice(0, 8)}`;
    const context = this.brain.claimAutoFix(findingId.trim(), id);
    const iso = () => new Date(this.now()).toISOString();

    const job = {
      id,
      findingId: context.finding.id,
      title: context.finding.title,
      severity: context.finding.severity,
      integration: context.integration,
      permission: context.playbook.autoFix.permission,
      status: 'running',
      steps: STEPS.map((s) => ({ ...s, status: 'pending', detail: null, startedAt: null, finishedAt: null })),
      scoreBefore: context.score,
      scoreAfter: null,
      error: null,
      startedAt: iso(),
      finishedAt: null,
    };
    this.jobs.set(id, job);
    this.#trim();

    const run = this.#run(job, context)
      .catch((error) => {
        // Defensive: #run handles its own failures; this guards against bugs.
        this.logger.error?.(error);
        this.#fail(job, null, 'Unexpected error while applying the fix.');
      })
      .finally(() => this.running.delete(id));
    this.running.set(id, run);
    return this.#view(job);
  }

  get(jobId) {
    const job = this.jobs.get(jobId);
    if (!job) throw notFound('Auto-Fix job');
    return this.#view(job);
  }

  /** Waits for one job (or all running jobs) to finish. */
  async settle(jobId) {
    if (jobId) return this.running.get(jobId);
    await Promise.all(this.running.values());
    return undefined;
  }

  reset() {
    this.jobs.clear();
  }

  async #run(job, context) {
    const { finding, playbook, integration, account } = context;

    await this.#step(job, 'validate', () => {
      return `${integration.name} connection active · just-in-time grant for ${playbook.autoFix.permission} on ` +
        `${finding.resource.name} (expires in 15 min)`;
    });
    if (job.status !== 'running') return;

    await this.#step(job, 'snapshot', () => {
      const snapshot = `snap_${job.id.slice(4)}`;
      return `Saved current configuration of ${finding.resource.type} ${finding.resource.name} as ${snapshot}. Rollback: ${playbook.rollback}`;
    });
    if (job.status !== 'running') return;

    await this.#step(job, 'execute', () => {
      const calls = playbook.actions.length ? playbook.actions : ['Apply remediation'];
      return `${calls.map((call) => `${call} → OK`).join(' · ')}${account?.label ? ` (${account.label})` : ''}`;
    });
    if (job.status !== 'running') return;

    await this.#step(job, 'verify', () => {
      if (!this.brain.completeAutoFix(job.findingId, job.id)) {
        throw new StepError(this.brain.autoFixBlocker(job.findingId, job.id) ?? 'The finding could not be resolved.');
      }
      return `Re-scanned ${finding.resource.name}: check passes. Finding marked resolved.`;
    });
    if (job.status !== 'running') return;

    await this.#step(job, 'rescore', () => {
      job.scoreAfter = this.brain.riskScore().score;
      const delta = job.scoreAfter - job.scoreBefore;
      return `Security score ${job.scoreBefore} → ${job.scoreAfter} (${delta >= 0 ? '+' : ''}${delta})`;
    });
    if (job.status !== 'running') return;

    job.status = 'succeeded';
    job.finishedAt = new Date(this.now()).toISOString();
  }

  async #step(job, key, perform) {
    const step = job.steps.find((s) => s.key === key);
    step.status = 'running';
    step.startedAt = new Date(this.now()).toISOString();
    if (this.stepMs) await sleep(this.stepMs);

    // Every step re-validates the claim: the integration can be paused or
    // disconnected, or the finding changed, while the fix is in flight.
    if (key !== 'verify' && key !== 'rescore') {
      const blocker = this.brain.autoFixBlocker(job.findingId, job.id);
      if (blocker) return this.#fail(job, step, blocker);
    }
    try {
      step.detail = perform();
      step.status = 'done';
      step.finishedAt = new Date(this.now()).toISOString();
    } catch (error) {
      this.#fail(job, step, error instanceof StepError ? error.message : 'Step failed unexpectedly.');
      if (!(error instanceof StepError)) this.logger.error?.(error);
    }
    return undefined;
  }

  #fail(job, step, message) {
    if (step) {
      step.status = 'failed';
      step.detail = message;
      step.finishedAt = new Date(this.now()).toISOString();
    }
    for (const s of job.steps) if (s.status === 'pending') s.status = 'skipped';
    job.status = 'failed';
    job.error = message;
    job.finishedAt = new Date(this.now()).toISOString();
    this.brain.releaseAutoFix(job.findingId, job.id);
  }

  #view(job) {
    return structuredClone(job);
  }

  #trim() {
    if (this.jobs.size <= JOB_LIMIT) return;
    for (const [id, job] of this.jobs) {
      if (this.jobs.size <= JOB_LIMIT) break;
      if (job.status !== 'running') this.jobs.delete(id);
    }
  }
}

class StepError extends Error {}
