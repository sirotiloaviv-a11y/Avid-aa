import { PEOPLE, REPOS, SECRET_TYPES, EXTERNAL_DOMAINS } from '../../mock/pools.js';

export default {
  id: 'github',
  name: 'GitHub',
  shortName: 'GH',
  vendor: 'GitHub',
  color: '#8b949e',
  description: 'Source code, secrets in commits, branch protection and organization access.',
  authMethod: 'GitHub App installation (read-only)',
  docsUrl: 'https://docs.github.com/en/apps',
  scopes: ['metadata:read', 'contents:read', 'administration:read', 'secret_scanning_alerts:read', 'members:read'],
  credentialFields: [
    {
      name: 'organization',
      label: 'Organization',
      placeholder: 'acme-corp',
      example: 'acme-corp',
      pattern: /^[a-z\d](?:[a-z\d]|-(?=[a-z\d])){0,38}$/i,
      patternMessage: 'Use the organization login, e.g. acme-corp',
      help: 'The GitHub organization login where the Veyra app is installed.',
    },
  ],
  accountFrom: ({ organization }) => ({
    key: organization.toLowerCase(),
    label: `github.com/${organization}`,
    organization,
  }),
  templates: [
    {
      key: 'exposed-secret',
      title: (r) => `Exposed ${r.secretType} in ${r.repo}`,
      severity: 'critical',
      category: 'Secrets',
      exposure: 'public',
      exploitability: 1.6,
      count: [1, 2],
      maxAgeDays: 6,
      resource: (rng, account) => {
        const secret = rng.pick(SECRET_TYPES);
        const repo = rng.pick(REPOS);
        return {
          id: `${account.key}/${repo}:${secret.file}`,
          name: `${repo}/${secret.file}`,
          type: 'Repository file',
          repo,
          secretType: secret.type,
          file: secret.file,
          preview: `${secret.prefix}${rng.alnum(4)}••••••••`,
          commit: rng.hex(7),
          author: rng.pick(PEOPLE),
        };
      },
      explain: (r) =>
        `A ${r.secretType} was pushed to ${r.file} in ${r.repo} (commit ${r.commit} by ${r.author}). ` +
        `Anyone with read access to the repository, and every fork and clone, now has this credential. ` +
        `Deleting the file does not help: the value stays in git history until the key is revoked.`,
      impact: 'Direct access to production systems or billing with the leaked credential.',
      remediation: [
        'Revoke and rotate the credential at the issuing provider immediately.',
        'Review the provider audit logs for use of the key since the commit date.',
        'Move the value to a secrets manager and reference it from CI/CD.',
        'Enable push protection for secret scanning on the organization.',
      ],
      effort: '15 min',
      frameworks: ['CIS GitHub 1.3.8', 'SOC 2 CC6.1', 'ISO 27001 A.8.24'],
      evidence: (r) => ({ commit: r.commit, file: r.file, match: r.preview, detector: 'secret-scanning' }),
    },
    {
      key: 'branch-protection-missing',
      title: (r) => `No branch protection on ${r.repo}:main`,
      severity: 'high',
      category: 'Configuration',
      exposure: 'internal',
      exploitability: 1.1,
      count: [1, 3],
      resource: (rng, account) => {
        const repo = rng.pick(REPOS);
        return { id: `${account.key}/${repo}#main`, name: `${repo}:main`, type: 'Branch', repo };
      },
      explain: (r) =>
        `The default branch of ${r.repo} accepts direct pushes and force-pushes without review. ` +
        `A single compromised developer account can ship code to production with no second pair of eyes.`,
      impact: 'Unreviewed code, including malicious changes, can reach production.',
      remediation: [
        'Add a ruleset requiring pull requests with at least one approving review.',
        'Require status checks to pass and block force-pushes and deletions.',
        'Apply the ruleset at organization level so new repositories inherit it.',
      ],
      effort: '10 min',
      frameworks: ['CIS GitHub 1.1.3', 'SOC 2 CC8.1'],
    },
    {
      key: 'members-without-2fa',
      title: (r) => `${r.count} organization members without two-factor authentication`,
      severity: 'high',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.3,
      resource: (rng, account) => {
        const users = rng.sample(PEOPLE, rng.int(3, 7));
        return { id: `${account.key}:2fa`, name: account.organization, type: 'Organization', count: users.length, users };
      },
      explain: (r, account) =>
        `${r.count} members of ${account.organization} sign in with a password only (${r.users.slice(0, 3).join(', ')}` +
        `${r.count > 3 ? ', …' : ''}). Credential stuffing or phishing on any of them yields write access to your code.`,
      impact: 'Account takeover leads to source code theft or supply-chain tampering.',
      remediation: [
        'Notify the listed members and give them a short deadline to enroll.',
        'Enable "Require two-factor authentication" in organization security settings.',
        'Prefer passkeys or security keys for administrators.',
      ],
      effort: '5 min',
      frameworks: ['CIS GitHub 1.3.5', 'SOC 2 CC6.1', 'NIST 800-63B'],
      evidence: (r) => ({ members: r.users }),
    },
    {
      key: 'dependabot-critical',
      title: (r) => `${r.count} critical dependency vulnerabilities in ${r.repo}`,
      severity: 'high',
      category: 'Vulnerabilities',
      exposure: 'public',
      count: [1, 2],
      resource: (rng, account) => {
        const repo = rng.pick(REPOS);
        const cves = Array.from({ length: rng.int(1, 4) }, () => `CVE-2026-${rng.int(10000, 49999)}`);
        return { id: `${account.key}/${repo}:deps`, name: repo, type: 'Repository', repo, count: cves.length, cves };
      },
      explain: (r) =>
        `${r.repo} depends on packages with known critical vulnerabilities (${r.cves.join(', ')}) ` +
        `that have had patched versions available for more than 30 days.`,
      impact: 'Remote code execution or data exposure through vulnerable third-party code.',
      remediation: [
        'Merge the open Dependabot pull requests, or bump the packages manually.',
        'Run the test suite and deploy the patched build.',
        'Enable Dependabot security updates on the repository.',
      ],
      effort: '30 min',
      frameworks: ['SOC 2 CC7.1', 'ISO 27001 A.8.8'],
      evidence: (r) => ({ cves: r.cves }),
    },
    {
      key: 'outside-collaborator-admin',
      title: (r) => `Outside collaborator has admin rights on ${r.repo}`,
      severity: 'medium',
      category: 'Identity',
      exposure: 'external',
      resource: (rng, account) => {
        const repo = rng.pick(REPOS);
        const user = `${rng.pick(['dev', 'contractor', 'freelance'])}-${rng.alnum(5, 'abcdefghijklmnopqrstuvwxyz')}`;
        return { id: `${account.key}/${repo}:${user}`, name: user, type: 'Collaborator', repo, user };
      },
      explain: (r) =>
        `${r.user} is not a member of your organization but holds admin permission on ${r.repo}. ` +
        `Admins can change settings, add deploy keys and delete the repository, outside your offboarding process.`,
      impact: 'Privileged access that survives contract end and bypasses SSO.',
      remediation: [
        'Confirm whether the engagement is still active.',
        'Downgrade to write (or remove) and route access through an organization team.',
      ],
      effort: '5 min',
      frameworks: ['CIS GitHub 1.3.3', 'SOC 2 CC6.2'],
    },
    {
      key: 'public-repo-internal',
      title: (r) => `Internal repository ${r.repo} is public`,
      severity: 'high',
      category: 'Data Exposure',
      exposure: 'public',
      probability: 0.5,
      resource: (rng, account) => {
        const repo = rng.pick(['infra-terraform', 'internal-tools', 'deploy-scripts']);
        return { id: `${account.key}/${repo}:visibility`, name: repo, type: 'Repository', repo };
      },
      explain: (r) =>
        `${r.repo} was switched to public visibility. It contains infrastructure layout and internal hostnames ` +
        `that make reconnaissance against your environment trivial.`,
      impact: 'Exposure of infrastructure details and potentially embedded credentials.',
      remediation: [
        'Change the repository visibility back to private.',
        'Run a secret scan over the full history, since forks may already exist.',
        'Restrict repository visibility changes to organization owners.',
      ],
      effort: '5 min',
      frameworks: ['CIS GitHub 1.2.2', 'SOC 2 C1.1'],
    },
    {
      key: 'deploy-key-write',
      title: (r) => `Deploy key with write access on ${r.repo}`,
      severity: 'medium',
      category: 'Secrets',
      exposure: 'internal',
      resource: (rng, account) => {
        const repo = rng.pick(REPOS);
        return { id: `${account.key}/${repo}:deploykey`, name: `${repo} deploy key`, type: 'Deploy key', repo, ageDays: rng.int(400, 1200) };
      },
      explain: (r) =>
        `A deploy key on ${r.repo} has write access and has not been rotated in ${r.ageDays} days. ` +
        `Whoever holds the private key can push code without any user identity attached.`,
      impact: 'Anonymous, long-lived write access to source code.',
      remediation: [
        'Replace the deploy key with a GitHub App or a read-only key.',
        'Delete the old key and audit recent pushes made with it.',
      ],
      effort: '20 min',
      frameworks: ['CIS GitHub 1.3.6'],
    },
    {
      key: 'external-email-member',
      title: (r) => `Organization owner uses personal email (${r.email})`,
      severity: 'low',
      category: 'Identity',
      exposure: 'external',
      probability: 0.6,
      resource: (rng, account) => {
        const email = `${rng.pick(PEOPLE)}@${rng.pick(EXTERNAL_DOMAINS.slice(0, 4))}`;
        return { id: `${account.key}:${email}`, name: email, type: 'Member', email };
      },
      explain: (r) =>
        `An organization owner's verified email is ${r.email}, a personal mailbox outside corporate controls. ` +
        `Password resets and security notices go to an inbox you cannot monitor or recover.`,
      impact: 'Owner account recovery controlled by an unmanaged mailbox.',
      remediation: [
        'Ask the owner to add and verify their corporate email.',
        'Enforce SAML SSO so access is tied to your identity provider.',
      ],
      effort: '5 min',
      frameworks: ['SOC 2 CC6.1'],
    },
  ],
};
