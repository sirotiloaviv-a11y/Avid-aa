import { PEOPLE, SLACK_CHANNELS, SENSITIVE_DOCS } from '../../mock/pools.js';

export default {
  id: 'slack',
  name: 'Slack',
  shortName: 'SL',
  vendor: 'Salesforce',
  color: '#e01e5a',
  description: 'File sharing, external connections, guest accounts, apps and workspace authentication.',
  authMethod: 'Slack app OAuth (admin read scopes)',
  docsUrl: 'https://api.slack.com/authentication/oauth-v2',
  scopes: ['admin.teams:read', 'admin.apps:read', 'team:read', 'users:read', 'files:read', 'channels:read'],
  credentialFields: [
    {
      name: 'workspace',
      label: 'Workspace URL',
      placeholder: 'acme',
      example: 'acme',
      pattern: /^[a-z\d][a-z\d-]{0,20}$/i,
      patternMessage: 'Use the subdomain only, e.g. acme for acme.slack.com',
      help: 'The part before .slack.com.',
    },
  ],
  accountFrom: ({ workspace }) => ({ key: workspace.toLowerCase(), label: `${workspace.toLowerCase()}.slack.com`, workspace: workspace.toLowerCase() }),
  templates: [
    {
      key: 'public-file-links',
      title: (r) => `${r.count} files shared via public links, including "${r.sample}"`,
      severity: 'high',
      category: 'Data Exposure',
      exposure: 'public',
      exploitability: 1.2,
      resource: (rng, account) => ({
        id: `${account.workspace}:public-files`,
        name: 'Public file links',
        type: 'Workspace setting',
        count: rng.int(24, 310),
        sample: rng.pick(SENSITIVE_DOCS),
      }),
      explain: (r) =>
        `Public file sharing is enabled for every member, and ${r.count} files currently have a live public URL ` +
        `(slack-files.com) that opens without signing in, including "${r.sample}". These links are routinely pasted ` +
        `into email and tickets and never expire.`,
      impact: 'Excessive file sharing permissions expose internal files to anyone with the URL.',
      remediation: [
        'Disable "Public file sharing" in workspace settings > Permissions.',
        'Revoke existing public links (Veyra lists them in the evidence).',
        'Restrict file sharing to workspace members and Slack Connect partners only.',
      ],
      effort: '10 min',
      frameworks: ['CIS Slack 2.3', 'SOC 2 C1.1'],
      evidence: (r, rng) => ({ publicLinks: r.count, examples: [r.sample, ...rng.sample(SENSITIVE_DOCS.filter((d) => d !== r.sample), 2)] }),
    },
    {
      key: 'external-sensitive-channel',
      title: (r) => `#${r.name} is shared with an external organization`,
      severity: 'medium',
      category: 'Data Exposure',
      exposure: 'external',
      count: [1, 2],
      resource: (rng, account) => {
        const name = rng.pick(SLACK_CHANNELS);
        return { id: `${account.workspace}:#${name}`, name, type: 'Slack Connect channel', partner: rng.pick(['Northwind Agency', 'Contoso Consulting', 'Initech Outsourcing']) };
      },
      explain: (r) =>
        `#${r.name} is connected to ${r.partner} through Slack Connect. The channel name suggests confidential discussions, ` +
        `and the full message history is visible to every member of the partner organization.`,
      impact: 'Confidential conversations readable by a third party.',
      remediation: [
        'Confirm the partnership still needs access; disconnect the organization if not.',
        'Move sensitive discussions to an internal-only channel.',
        'Require admin approval for new Slack Connect invitations.',
      ],
      effort: '10 min',
      frameworks: ['SOC 2 CC6.7'],
    },
    {
      key: 'admin-scoped-app',
      title: (r) => `App "${r.name}" has admin and full message history scopes`,
      severity: 'high',
      category: 'Third-Party',
      exposure: 'external',
      resource: (rng, account) => {
        const name = rng.pick(['StandupBot', 'Export Everything', 'Meeting Notes AI', 'HR Pulse']);
        return { id: `${account.workspace}:app:${name}`, name, type: 'Slack app', installer: rng.pick(PEOPLE) };
      },
      explain: (r) =>
        `"${r.name}", installed by ${r.installer}, holds admin, channels:history and files:read across all channels. ` +
        `A breach at the vendor would expose your entire Slack history.`,
      impact: 'Third party can read every message and file in the workspace.',
      remediation: [
        'Review whether the app needs workspace-wide history; reinstall with narrower scopes.',
        'Turn on app approval so members cannot install apps with admin scopes.',
      ],
      effort: '15 min',
      frameworks: ['CIS Slack 3.1', 'SOC 2 CC9.2'],
    },
    {
      key: 'no-2fa',
      title: 'Two-factor authentication is not required for the workspace',
      severity: 'high',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.2,
      resource: (rng, account) => ({ id: `${account.workspace}:2fa`, name: `${account.workspace}.slack.com`, type: 'Workspace setting', without: rng.int(30, 140) }),
      explain: (r) =>
        `Workspace-wide 2FA is off and SSO is not enforced. ${r.without} members sign in with a password only, ` +
        `which gives a phisher access to internal conversations, often including credentials.`,
      impact: 'Account takeover exposes internal discussions and shared secrets.',
      remediation: ['Enforce SSO through your identity provider, or require 2FA for all members.'],
      effort: '10 min',
      frameworks: ['CIS Slack 1.1', 'SOC 2 CC6.1'],
    },
    {
      key: 'guest-no-expiry',
      title: (r) => `${r.count} guest accounts with no expiration date`,
      severity: 'medium',
      category: 'Identity',
      exposure: 'external',
      resource: (rng, account) => ({ id: `${account.workspace}:guests`, name: 'Guest accounts', type: 'Users', count: rng.int(6, 38), oldest: rng.int(200, 700) }),
      explain: (r) =>
        `${r.count} single- and multi-channel guests have no expiration. The oldest has had access for ${r.oldest} days, ` +
        `long after most contractor engagements end.`,
      impact: 'Former contractors retain access to internal channels.',
      remediation: ['Set a default expiration for guest accounts.', 'Deactivate guests inactive for more than 30 days.'],
      effort: '15 min',
      frameworks: ['SOC 2 CC6.2'],
    },
    {
      key: 'unlimited-retention',
      title: 'Messages and files are retained forever',
      severity: 'low',
      category: 'Configuration',
      exposure: 'internal',
      probability: 0.8,
      resource: (rng, account) => ({ id: `${account.workspace}:retention`, name: 'Retention policy', type: 'Workspace setting', years: rng.int(3, 9) }),
      explain: (r) =>
        `No retention policy is configured, so ${r.years} years of messages and files are kept indefinitely. Everything ever ` +
        `pasted into Slack, including passwords and customer data, remains available to anyone who gets in.`,
      impact: 'Larger blast radius for any account or token compromise.',
      remediation: ['Define a retention policy aligned with legal requirements (e.g. 1-2 years).'],
      effort: '10 min',
      frameworks: ['GDPR Art. 5(1)(e)', 'ISO 27001 A.5.33'],
    },
  ],
};
