import { PEOPLE, EXTERNAL_DOMAINS, SENSITIVE_DOCS, OAUTH_APPS } from '../../mock/pools.js';

export default {
  id: 'google-workspace',
  name: 'Google Workspace',
  shortName: 'GW',
  vendor: 'Google',
  color: '#4285f4',
  description: 'Admin roles, 2-Step Verification, Drive sharing and third-party OAuth apps.',
  authMethod: 'OAuth consent + domain-wide delegation (read-only)',
  docsUrl: 'https://support.google.com/a/answer/162106',
  scopes: [
    'admin.directory.user.readonly',
    'admin.directory.rolemanagement.readonly',
    'admin.reports.audit.readonly',
    'drive.metadata.readonly',
  ],
  credentialFields: [
    {
      name: 'domain',
      label: 'Primary domain',
      placeholder: 'acme.com',
      example: 'acme.com',
      pattern: /^(?=.{3,253}$)([a-z\d](?:[a-z\d-]{0,61}[a-z\d])?\.)+[a-z]{2,63}$/i,
      patternMessage: 'Enter a domain like acme.com',
      help: 'Primary domain of your Google Workspace tenant.',
    },
    {
      name: 'adminEmail',
      label: 'Super admin email',
      placeholder: 'it-admin@acme.com',
      example: 'it-admin@acme.com',
      pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
      patternMessage: 'Enter a valid email address',
      help: 'The admin who will approve the OAuth consent screen.',
    },
  ],
  accountFrom: ({ domain }) => ({ key: domain.toLowerCase(), label: domain.toLowerCase(), domain: domain.toLowerCase() }),
  templates: [
    {
      key: 'unverified-external-admin',
      title: (r) => `External account ${r.email} holds Super Admin`,
      severity: 'critical',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.5,
      maxAgeDays: 10,
      resource: (rng) => {
        const email = `${rng.pick(PEOPLE)}@${rng.pick(EXTERNAL_DOMAINS)}`;
        return { id: `admin:${email}`, name: email, type: 'Admin role assignment', email, grantedBy: `${rng.pick(PEOPLE)}`, role: 'Super Admin' };
      },
      explain: (r, account) =>
        `${r.email} is outside ${account.domain}, has never completed identity verification, and was granted the ` +
        `Super Admin role by ${r.grantedBy}. Super Admins can read any mailbox, reset any password and disable security controls. ` +
        `Your organization cannot enforce MFA, device policy or offboarding on this account.`,
      impact: 'Full tenant takeover through an identity you do not control.',
      remediation: [
        'Revoke the Super Admin role from the external account now.',
        'Confirm with the granting admin why the role was assigned.',
        'Review the Admin audit log for actions taken by this account.',
        'Restrict admin roles to managed accounts in your primary domain.',
      ],
      effort: '5 min',
      frameworks: ['CIS Google Workspace 1.1.3', 'SOC 2 CC6.2', 'ISO 27001 A.5.18'],
      evidence: (r) => ({ role: r.role, verified: false, grantedBy: r.grantedBy }),
    },
    {
      key: 'admins-without-2sv',
      title: (r) => `${r.count} admins are not enrolled in 2-Step Verification`,
      severity: 'high',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.3,
      resource: (rng, account) => {
        const admins = rng.sample(PEOPLE, rng.int(2, 4)).map((p) => `${p}@${account.domain}`);
        return { id: `${account.domain}:admins-2sv`, name: 'Administrators', type: 'Admin accounts', count: admins.length, admins };
      },
      explain: (r) =>
        `${r.count} accounts with admin privileges (${r.admins.slice(0, 2).join(', ')}${r.count > 2 ? ', …' : ''}) ` +
        `can sign in with a password alone. Admin accounts are the first target of phishing campaigns.`,
      impact: 'Phished admin password gives control of users, email and data.',
      remediation: [
        'Enforce 2-Step Verification for the admin organizational unit.',
        'Require security keys or passkeys for Super Admins.',
      ],
      effort: '10 min',
      frameworks: ['CIS Google Workspace 4.1.1.1', 'SOC 2 CC6.1'],
      evidence: (r) => ({ admins: r.admins }),
    },
    {
      key: 'drive-public-sensitive',
      title: (r) => `"${r.name}" is shared with anyone who has the link`,
      severity: 'high',
      category: 'Data Exposure',
      exposure: 'public',
      count: [2, 3],
      resource: (rng, account) => {
        const name = rng.pick(SENSITIVE_DOCS);
        return { id: `drive:${name}`, name, type: 'Drive file', owner: `${rng.pick(PEOPLE)}@${account.domain}`, views: rng.int(4, 230) };
      },
      explain: (r) =>
        `"${r.name}", owned by ${r.owner}, is shared as "Anyone with the link can view" and has ${r.views} views from ` +
        `outside your domain in the last 30 days. Links get forwarded, pasted into tickets and indexed.`,
      impact: 'Sensitive business data readable by anyone who obtains the link.',
      remediation: [
        'Change link sharing to "Restricted" and share with named people only.',
        'Set the domain default for new files to "Restricted".',
        'Enable DLP rules that block public sharing of files matching sensitive labels.',
      ],
      effort: '5 min',
      frameworks: ['CIS Google Workspace 3.1.3.1.1', 'SOC 2 C1.1', 'GDPR Art. 32'],
    },
    {
      key: 'risky-oauth-app',
      title: (r) => `Unverified app "${r.name}" can read all Drive and Gmail data`,
      severity: 'high',
      category: 'Third-Party',
      exposure: 'external',
      resource: (rng) => {
        const app = rng.pick(OAUTH_APPS);
        return { id: `oauth:${app.name}`, name: app.name, type: 'OAuth app', publisher: app.publisher, users: rng.int(3, 64) };
      },
      explain: (r) =>
        `${r.users} users granted "${r.name}" (${r.publisher}) full read access to Gmail and Drive. The app has not ` +
        `passed Google verification and its tokens keep working even after users change their password.`,
      impact: 'Silent, persistent data access by an unvetted third party.',
      remediation: [
        'Block the app in Admin console > Security > API controls.',
        'Revoke existing tokens for all users.',
        'Switch third-party access to "Only trusted apps can access Google data".',
      ],
      effort: '10 min',
      frameworks: ['CIS Google Workspace 5.1.1.2', 'SOC 2 CC9.2'],
    },
    {
      key: 'auto-forwarding',
      title: (r) => `Mail auto-forwarding to ${r.target}`,
      severity: 'medium',
      category: 'Data Exposure',
      exposure: 'external',
      probability: 0.75,
      resource: (rng, account) => {
        const user = `${rng.pick(PEOPLE)}@${account.domain}`;
        const target = `${rng.pick(PEOPLE)}@${rng.pick(EXTERNAL_DOMAINS.slice(0, 4))}`;
        return { id: `fwd:${user}`, name: user, type: 'Mailbox', target };
      },
      explain: (r) =>
        `${r.name} forwards every incoming email to ${r.target}, a personal mailbox. Auto-forwarding is also a classic ` +
        `persistence technique after a mailbox compromise.`,
      impact: 'Continuous leak of business email to an unmanaged account.',
      remediation: [
        'Remove the forwarding rule and confirm with the user why it existed.',
        'Disable automatic forwarding to external addresses in Gmail settings.',
      ],
      effort: '5 min',
      frameworks: ['CIS Google Workspace 3.1.3.4.3.1', 'SOC 2 CC6.7'],
    },
    {
      key: 'dormant-admin',
      title: (r) => `Admin account ${r.name} inactive for ${r.days} days`,
      severity: 'medium',
      category: 'Identity',
      exposure: 'internal',
      resource: (rng, account) => {
        const name = `${rng.pick(PEOPLE)}@${account.domain}`;
        return { id: `dormant:${name}`, name, type: 'User', days: rng.int(95, 400) };
      },
      explain: (r) =>
        `${r.name} still holds admin privileges but has not signed in for ${r.days} days, which usually means a departed employee ` +
        `or a forgotten service account that nobody would notice being misused.`,
      impact: 'Unmonitored privileged account available to attackers.',
      remediation: ['Suspend the account or remove its admin role.', 'Add admin role review to the quarterly access review.'],
      effort: '5 min',
      frameworks: ['SOC 2 CC6.2', 'ISO 27001 A.5.18'],
    },
  ],
};
