// Compliance posture: readiness against SOC 2 and ISO/IEC 27001:2022.
//
// Every security check maps to framework controls: explicitly, through the
// references in its `frameworks` list, and implicitly, through its category
// (an Identity check always evidences access-control controls, a Logging check
// always evidences monitoring controls, and so on).
//
// A control is "assessed" when at least one monitored integration runs a check
// mapped to it. Each mapped check scores 1 when it passes, 0.5 when it only has
// medium/low findings open, and 0 when a critical/high finding is open. The
// control's score is the mean over its checks, and its status is:
//   failing  - at least one critical/high finding maps to it
//   partial  - only medium/low findings map to it
//   passing  - no open finding maps to it
// readiness = mean control score, so every fix moves it.

export const FRAMEWORKS = [
  {
    id: 'soc2',
    name: 'SOC 2',
    fullName: 'SOC 2 Type II (Trust Services Criteria)',
    prefix: 'SOC 2 ',
    controls: {
      'CC6.1': 'Logical access security software, infrastructure and architectures',
      'CC6.2': 'User registration, authorization and de-provisioning',
      'CC6.3': 'Role-based access and least privilege',
      'CC6.6': 'Boundary protection against threats from outside the system',
      'CC6.7': 'Restriction of data transmission and movement',
      'CC7.1': 'Detection of configuration changes and vulnerabilities',
      'CC7.2': 'Monitoring of system components for anomalies',
      'CC7.3': 'Evaluation of security events',
      'CC8.1': 'Change management',
      'CC9.2': 'Vendor and business partner risk management',
      'C1.1': 'Identification and protection of confidential information',
    },
    byCategory: {
      Identity: ['CC6.1', 'CC6.2', 'CC6.3'],
      'Data Exposure': ['C1.1', 'CC6.7'],
      Secrets: ['CC6.1'],
      Network: ['CC6.6'],
      Logging: ['CC7.2'],
      'Third-Party': ['CC9.2'],
      Vulnerabilities: ['CC7.1'],
      Configuration: ['CC7.1', 'CC8.1'],
    },
  },
  {
    id: 'iso27001',
    name: 'ISO 27001',
    fullName: 'ISO/IEC 27001:2022 Annex A',
    prefix: 'ISO 27001 ',
    controls: {
      'A.5.15': 'Access control',
      'A.5.17': 'Authentication information',
      'A.5.18': 'Access rights',
      'A.5.19': 'Information security in supplier relationships',
      'A.5.23': 'Information security for use of cloud services',
      'A.5.33': 'Protection of records',
      'A.8.5': 'Secure authentication',
      'A.8.8': 'Management of technical vulnerabilities',
      'A.8.9': 'Configuration management',
      'A.8.12': 'Data leakage prevention',
      'A.8.13': 'Information backup',
      'A.8.15': 'Logging',
      'A.8.16': 'Monitoring activities',
      'A.8.20': 'Networks security',
      'A.8.24': 'Use of cryptography',
    },
    byCategory: {
      Identity: ['A.5.15', 'A.5.18', 'A.8.5'],
      'Data Exposure': ['A.8.12', 'A.5.15'],
      Secrets: ['A.5.17', 'A.8.24'],
      Network: ['A.8.20'],
      Logging: ['A.8.15', 'A.8.16'],
      'Third-Party': ['A.5.19', 'A.5.23'],
      Vulnerabilities: ['A.8.8'],
      Configuration: ['A.8.9'],
    },
  },
];

/** Controls of one framework that a check (template or finding) evidences. */
export function controlsFor(framework, item) {
  const ids = new Set(framework.byCategory[item.category] ?? []);
  for (const ref of item.frameworks ?? []) {
    if (!ref.startsWith(framework.prefix)) continue;
    const id = ref.slice(framework.prefix.length).trim();
    if (framework.controls[id]) ids.add(id);
  }
  return [...ids];
}

const BLOCKING = new Set(['critical', 'high']);

/**
 * @param {{ provider: string, key: string, category: string, frameworks?: string[] }[]} assessedChecks
 *        every check run by a monitored integration (failing templates and passing baseline checks)
 * @param {{ provider: string, templateKey: string, severity: string }[]} openFindings
 */
export function computeCompliance(assessedChecks, openFindings) {
  // Worst open severity per check: 0 = blocking, 0.5 = minor.
  const checkScore = new Map();
  const openCount = new Map();
  for (const finding of openFindings) {
    const key = `${finding.provider}:${finding.templateKey}`;
    const score = BLOCKING.has(finding.severity) ? 0 : 0.5;
    checkScore.set(key, Math.min(checkScore.get(key) ?? 1, score));
    openCount.set(key, (openCount.get(key) ?? 0) + 1);
  }

  return FRAMEWORKS.map((framework) => {
    const byControl = new Map();
    for (const check of assessedChecks) {
      for (const id of controlsFor(framework, check)) {
        const list = byControl.get(id) ?? [];
        list.push(`${check.provider}:${check.key}`);
        byControl.set(id, list);
      }
    }

    const controls = [...byControl.entries()].sort(([a], [b]) => a.localeCompare(b, 'en', { numeric: true })).map(([id, checks]) => {
      const scores = checks.map((key) => checkScore.get(key) ?? 1);
      const worst = Math.min(...scores);
      return {
        id,
        name: framework.controls[id],
        status: worst === 1 ? 'passing' : worst === 0 ? 'failing' : 'partial',
        score: scores.reduce((sum, v) => sum + v, 0) / scores.length,
        checks: checks.length,
        openFindings: checks.reduce((sum, key) => sum + (openCount.get(key) ?? 0), 0),
      };
    });
    const count = (status) => controls.filter((c) => c.status === status).length;
    const passing = count('passing');
    const partial = count('partial');
    const failing = count('failing');
    const readiness = controls.length
      ? Math.round((controls.reduce((sum, c) => sum + c.score, 0) / controls.length) * 100)
      : null;

    return {
      id: framework.id,
      name: framework.name,
      fullName: framework.fullName,
      readiness,
      assessed: controls.length,
      passing,
      partial,
      failing,
      controls,
      topGaps: controls
        .filter((c) => c.status !== 'passing')
        .sort((a, b) => a.score - b.score || b.openFindings - a.openFindings)
        .slice(0, 5),
    };
  });
}
