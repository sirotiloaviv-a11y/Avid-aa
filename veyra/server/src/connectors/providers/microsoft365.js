import { PEOPLE, EXTERNAL_DOMAINS, SENSITIVE_DOCS } from '../../mock/pools.js';

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default {
  id: 'microsoft-365',
  name: 'Microsoft 365',
  shortName: 'M365',
  vendor: 'Microsoft',
  color: '#d83b01',
  description: 'Entra ID sign-in policy, Exchange Online, SharePoint and OneDrive sharing.',
  authMethod: 'Entra ID admin consent (Microsoft Graph, application read-only)',
  docsUrl: 'https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent',
  scopes: ['Directory.Read.All', 'Policy.Read.All', 'AuditLog.Read.All', 'Sites.Read.All', 'MailboxSettings.Read'],
  credentialFields: [
    {
      name: 'tenantId',
      label: 'Tenant ID',
      placeholder: '00000000-0000-0000-0000-000000000000',
      example: '6f1c2a9e-3b4d-4e8f-9a1b-2c3d4e5f6a7b',
      pattern: GUID,
      patternMessage: 'Tenant ID must be a GUID',
      help: 'Found in Entra admin center > Overview.',
    },
    {
      name: 'tenantDomain',
      label: 'Tenant domain',
      placeholder: 'acme.onmicrosoft.com',
      example: 'acme.onmicrosoft.com',
      pattern: /^[a-z\d][a-z\d-]{0,62}\.onmicrosoft\.com$/i,
      patternMessage: 'Expected <name>.onmicrosoft.com',
      help: 'Your initial *.onmicrosoft.com domain.',
    },
  ],
  accountFrom: ({ tenantId, tenantDomain }) => ({
    key: tenantId.toLowerCase(),
    label: tenantDomain.toLowerCase(),
    tenantId: tenantId.toLowerCase(),
    domain: tenantDomain.toLowerCase().replace('.onmicrosoft.com', '.com'),
  }),
  templates: [
    {
      key: 'mfa-not-enforced',
      title: (r) => `MFA not enforced for ${r.percent}% of users`,
      severity: 'critical',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.4,
      resource: (rng, account) => ({ id: `${account.tenantId}:mfa`, name: 'Conditional Access', type: 'Policy', percent: rng.int(18, 46), users: rng.int(40, 220) }),
      explain: (r) =>
        `No Conditional Access policy requires MFA for all users, and Security Defaults are off. ${r.users} accounts ` +
        `(${r.percent}% of the tenant) can sign in to Outlook, Teams and SharePoint with a password alone.`,
      impact: 'Password spray and phishing lead directly to mailbox and file access.',
      remediation: [
        'Create a Conditional Access policy requiring MFA for all users and all cloud apps.',
        'Exclude two monitored break-glass accounts only.',
        'Start in report-only mode for a day, then enforce.',
      ],
      effort: '20 min',
      frameworks: ['CIS M365 5.2.2.2', 'SOC 2 CC6.1', 'NIST 800-63B'],
    },
    {
      key: 'legacy-auth',
      title: 'Legacy authentication protocols are allowed',
      severity: 'high',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.3,
      resource: (rng, account) => ({ id: `${account.tenantId}:legacy-auth`, name: 'IMAP / POP / SMTP AUTH', type: 'Tenant setting', signIns: rng.int(80, 2400) }),
      explain: (r) =>
        `Basic authentication over IMAP, POP and SMTP AUTH is still accepted and recorded ${r.signIns} sign-ins last week. ` +
        `These protocols cannot do MFA, so they let attackers bypass it entirely.`,
      impact: 'MFA bypass for password spraying attacks.',
      remediation: [
        'Block legacy authentication with a Conditional Access policy.',
        'Disable SMTP AUTH at tenant level and re-enable per mailbox only where required.',
      ],
      effort: '15 min',
      frameworks: ['CIS M365 5.2.2.3', 'SOC 2 CC6.1'],
    },
    {
      key: 'external-forwarding-rule',
      title: (r) => `Inbox rule forwards ${r.name}'s mail to ${r.target}`,
      severity: 'high',
      category: 'Data Exposure',
      exposure: 'external',
      maxAgeDays: 8,
      resource: (rng, account) => {
        const user = `${rng.pick(PEOPLE)}@${account.domain}`;
        return { id: `rule:${user}`, name: user, type: 'Mailbox rule', target: `${rng.pick(PEOPLE)}@${rng.pick(EXTERNAL_DOMAINS)}`, ruleName: rng.pick(['.', '..', 'RSS Sync', 'x']) };
      },
      explain: (r) =>
        `A hidden inbox rule named "${r.ruleName}" on ${r.name} forwards messages containing "invoice" or "payment" to ${r.target} ` +
        `and deletes the original. This pattern is a strong indicator of business email compromise.`,
      impact: 'Ongoing interception of financial email; likely active compromise.',
      remediation: [
        'Delete the rule and revoke all sessions for the user.',
        'Reset the password and re-register MFA methods.',
        'Search the unified audit log for the sign-in that created the rule.',
        'Block automatic external forwarding in the outbound spam policy.',
      ],
      effort: '30 min',
      frameworks: ['CIS M365 6.2.1', 'SOC 2 CC7.3'],
      evidence: (r) => ({ ruleName: r.ruleName, forwardTo: r.target, deleteOriginal: true }),
    },
    {
      key: 'sharepoint-anyone-links',
      title: (r) => `SharePoint "Anyone" link on ${r.name}`,
      severity: 'high',
      category: 'Data Exposure',
      exposure: 'public',
      count: [1, 2],
      resource: (rng) => {
        const name = rng.pick(SENSITIVE_DOCS);
        return { id: `spo:${name}`, name, type: 'SharePoint file', site: rng.pick(['Finance', 'HR', 'Leadership', 'Legal']) };
      },
      explain: (r) =>
        `"${r.name}" on the ${r.site} site has an "Anyone with the link" sharing link with no expiration. ` +
        `No sign-in is required to open it, so access cannot be audited or revoked per person.`,
      impact: 'Anonymous access to confidential documents.',
      remediation: [
        'Remove the Anyone link and share with specific people.',
        'Limit external sharing to "New and existing guests" at the tenant level.',
        'Require Anyone links to expire within 7 days where they remain allowed.',
      ],
      effort: '10 min',
      frameworks: ['CIS M365 7.2.3', 'SOC 2 C1.1'],
    },
    {
      key: 'too-many-global-admins',
      title: (r) => `${r.count} Global Administrators (recommended: 2-4)`,
      severity: 'medium',
      category: 'Identity',
      exposure: 'internal',
      resource: (rng, account) => ({ id: `${account.tenantId}:ga`, name: 'Global Administrator', type: 'Directory role', count: rng.int(7, 14) }),
      explain: (r) =>
        `${r.count} accounts hold the Global Administrator role permanently. Every extra standing admin is another account ` +
        `whose compromise means tenant compromise.`,
      impact: 'Larger privileged attack surface and weaker accountability.',
      remediation: [
        'Reduce permanent Global Admins to 2-4, including break-glass accounts.',
        'Move other admins to least-privilege roles via Privileged Identity Management.',
      ],
      effort: '1 hr',
      frameworks: ['CIS M365 1.1.3', 'SOC 2 CC6.3'],
    },
    {
      key: 'audit-disabled',
      title: 'Mailbox auditing disabled for some users',
      severity: 'medium',
      category: 'Logging',
      exposure: 'internal',
      probability: 0.6,
      resource: (rng, account) => ({ id: `${account.tenantId}:audit`, name: 'Mailbox audit', type: 'Tenant setting', mailboxes: rng.int(5, 40) }),
      explain: (r) =>
        `Auditing is bypassed for ${r.mailboxes} mailboxes, so mailbox access by attackers or delegates leaves no trace.`,
      impact: 'Incomplete evidence during a mailbox-compromise investigation.',
      remediation: ['Remove the audit bypass associations.', 'Confirm AuditDisabled is False at the organization level.'],
      effort: '10 min',
      frameworks: ['CIS M365 6.1.2', 'SOC 2 CC7.2'],
    },
  ],
};
