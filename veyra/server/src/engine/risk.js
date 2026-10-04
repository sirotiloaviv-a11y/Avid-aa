// Risk scoring.
//
// Each open finding carries a penalty: its severity weight, scaled up when the
// affected resource is reachable from outside the organization. The score
// decays exponentially with the total penalty, so it never goes negative,
// the first few critical issues move it a lot, and fixing anything always
// moves it up. Coverage (how many integrations feed the score) is reported
// next to the score rather than folded into it, so connecting a new source
// that surfaces real problems lowers the score honestly instead of inflating it.

export const SEVERITIES = ['critical', 'high', 'medium', 'low'];

export const SEVERITY_WEIGHT = { critical: 10, high: 5, medium: 2, low: 0.5 };

export const EXPOSURE_MULTIPLIER = { public: 1.5, external: 1.25, internal: 1 };

/** Penalty points at which the overall score falls to ~37 (1/e). */
export const OVERALL_SCALE = 200;
/** Per-integration and per-category scores use a tighter scale. */
export const SCOPED_SCALE = 60;

export function findingPenalty(finding) {
  const weight = SEVERITY_WEIGHT[finding.severity] ?? 0;
  const exposure = EXPOSURE_MULTIPLIER[finding.exposure] ?? 1;
  return weight * exposure;
}

export function scoreFromPenalty(penalty, scale = OVERALL_SCALE) {
  return Math.round(100 * Math.exp(-penalty / scale));
}

export function gradeFor(score) {
  if (score >= 90) return { grade: 'A', label: 'Strong' };
  if (score >= 80) return { grade: 'B', label: 'Good' };
  if (score >= 70) return { grade: 'C', label: 'Fair' };
  if (score >= 55) return { grade: 'D', label: 'At risk' };
  return { grade: 'F', label: 'Critical' };
}

export function countBySeverity(findings) {
  const counts = Object.fromEntries(SEVERITIES.map((s) => [s, 0]));
  for (const finding of findings) counts[finding.severity] = (counts[finding.severity] ?? 0) + 1;
  return counts;
}

const sumPenalty = (findings) => findings.reduce((total, f) => total + findingPenalty(f), 0);

/**
 * @param {object[]} openFindings findings that are not resolved, from monitored integrations
 * @param {{ id: string, name: string }[]} monitoredIntegrations connected and enabled integrations
 * @param {number} totalIntegrations number of supported integrations
 */
export function computeRiskScore(openFindings, monitoredIntegrations, totalIntegrations) {
  const penalty = sumPenalty(openFindings);
  const score = scoreFromPenalty(penalty);

  const byIntegration = monitoredIntegrations.map(({ id, name }) => {
    const scoped = openFindings.filter((f) => f.provider === id);
    const scopedScore = scoreFromPenalty(sumPenalty(scoped), SCOPED_SCALE);
    return { id, name, score: scopedScore, ...gradeFor(scopedScore), open: scoped.length, counts: countBySeverity(scoped) };
  });

  const categories = new Map();
  for (const finding of openFindings) {
    const entry = categories.get(finding.category) ?? { category: finding.category, penalty: 0, open: 0 };
    entry.penalty += findingPenalty(finding);
    entry.open += 1;
    categories.set(finding.category, entry);
  }
  const byCategory = [...categories.values()]
    .map((entry) => ({
      ...entry,
      penalty: Math.round(entry.penalty * 10) / 10,
      share: penalty ? Math.round((entry.penalty / penalty) * 100) : 0,
    }))
    .sort((a, b) => b.penalty - a.penalty);

  return {
    score,
    ...gradeFor(score),
    penalty: Math.round(penalty * 10) / 10,
    counts: countBySeverity(openFindings),
    open: openFindings.length,
    coverage: {
      monitored: monitoredIntegrations.length,
      total: totalIntegrations,
      percent: totalIntegrations ? Math.round((monitoredIntegrations.length / totalIntegrations) * 100) : 0,
    },
    byIntegration,
    byCategory,
  };
}

/** Points the overall score would gain if this one finding were fixed. */
export function projectedGain(finding, openFindings) {
  const penalty = sumPenalty(openFindings);
  return scoreFromPenalty(penalty - findingPenalty(finding)) - scoreFromPenalty(penalty);
}
