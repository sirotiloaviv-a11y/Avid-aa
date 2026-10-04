import { findingPenalty, projectedGain, SEVERITIES } from './risk.js';

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Priority = risk penalty × how easy the issue is to exploit × an ageing
 * factor (an issue that has been open for weeks is more likely to have been
 * found by someone else). Severity is still the first sort key, so a medium
 * issue is never ranked above a critical one, whatever its exposure.
 */
export function priorityOf(finding, now = Date.now()) {
  const ageDays = Math.max(0, (now - Date.parse(finding.detectedAt)) / DAY_MS);
  const ageing = 1 + Math.min(ageDays / 60, 0.5);
  return Math.round(findingPenalty(finding) * (finding.exploitability ?? 1) * ageing * 10) / 10;
}

export function buildRecommendations(openFindings, integrationsById, { limit, now = Date.now() } = {}) {
  const ranked = openFindings
    .map((finding) => ({ finding, priority: priorityOf(finding, now) }))
    .sort((a, b) =>
      SEVERITIES.indexOf(a.finding.severity) - SEVERITIES.indexOf(b.finding.severity) ||
      b.priority - a.priority ||
      a.finding.detectedAt.localeCompare(b.finding.detectedAt));

  const selected = typeof limit === 'number' ? ranked.slice(0, limit) : ranked;

  return selected.map(({ finding, priority }, index) => {
    const integration = integrationsById.get(finding.provider);
    return {
      rank: index + 1,
      priority,
      projectedGain: projectedGain(finding, openFindings),
      findingId: finding.id,
      title: finding.title,
      severity: finding.severity,
      category: finding.category,
      exposure: finding.exposure,
      status: finding.status,
      explanation: finding.explanation,
      impact: finding.impact,
      remediation: finding.remediation,
      effort: finding.effort,
      frameworks: finding.frameworks,
      resource: { name: finding.resource.name, type: finding.resource.type },
      detectedAt: finding.detectedAt,
      integration: integration
        ? { id: integration.id, name: integration.name, shortName: integration.shortName, color: integration.color }
        : { id: finding.provider, name: finding.provider, shortName: finding.provider, color: '#64748b' },
    };
  });
}
