import { createRng, stableId } from '../lib/rng.js';

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Turn a provider's finding templates into concrete findings for one scan.
 *
 * Resources are generated from a generator seeded by provider, account and
 * template only, so the same misconfiguration keeps the same identity across
 * rescans. Only templates marked with a `probability` below 1 ("drift") vary
 * between scans, which simulates new issues appearing over time.
 */
export function generateFindings(provider, { account, scanNumber = 0, now = Date.now() }) {
  const accountKey = provider.accountKey(account);
  const scanRng = createRng(`${provider.id}:${accountKey}:scan:${scanNumber}`);
  const findings = [];

  for (const template of provider.templates) {
    const probability = template.probability ?? 1;
    if (probability < 1 && !scanRng.chance(probability)) continue;

    const rng = createRng(`${provider.id}:${accountKey}:${template.key}`);
    const [min, max] = template.count ?? [1, 1];
    const instances = rng.int(min, max);
    const seen = new Set();

    for (let i = 0; i < instances; i++) {
      const resource = template.resource(rng, account);
      if (seen.has(resource.id)) continue;
      seen.add(resource.id);

      const ageDays = rng.int(1, template.maxAgeDays ?? 45);
      findings.push({
        id: stableId('fnd', provider.id, template.key, resource.id),
        provider: provider.id,
        templateKey: template.key,
        title: typeof template.title === 'function' ? template.title(resource) : template.title,
        severity: template.severity,
        category: template.category,
        exposure: template.exposure ?? 'internal',
        exploitability: template.exploitability ?? 1,
        resource,
        explanation: template.explain(resource, account),
        impact: template.impact,
        remediation: template.remediation,
        effort: template.effort,
        frameworks: template.frameworks ?? [],
        evidence: template.evidence ? template.evidence(resource, rng, account) : {},
        detectedAt: new Date(now - ageDays * DAY_MS - rng.int(0, DAY_MS)).toISOString(),
        status: 'open',
      });
    }
  }

  return findings;
}
