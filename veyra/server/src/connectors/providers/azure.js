import { AZURE_REGIONS, BUCKET_PURPOSES, EXTERNAL_DOMAINS, PEOPLE } from '../../mock/pools.js';

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default {
  id: 'azure',
  name: 'Microsoft Azure',
  shortName: 'AZ',
  vendor: 'Microsoft',
  color: '#0078d4',
  description: 'Storage exposure, NSG rules, Key Vault protection, RBAC and Defender coverage.',
  authMethod: 'Service principal with Reader + Security Reader roles',
  docsUrl: 'https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles',
  scopes: ['Reader', 'Security Reader'],
  credentialFields: [
    {
      name: 'tenantId',
      label: 'Tenant ID',
      placeholder: '00000000-0000-0000-0000-000000000000',
      example: '6f1c2a9e-3b4d-4e8f-9a1b-2c3d4e5f6a7b',
      pattern: GUID,
      patternMessage: 'Tenant ID must be a GUID',
      help: 'Entra ID tenant that owns the subscription.',
    },
    {
      name: 'subscriptionId',
      label: 'Subscription ID',
      placeholder: '00000000-0000-0000-0000-000000000000',
      example: '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d',
      pattern: GUID,
      patternMessage: 'Subscription ID must be a GUID',
      help: 'The subscription to monitor. Management groups are supported in production.',
    },
  ],
  accountFrom: ({ subscriptionId, tenantId }) => ({
    key: subscriptionId.toLowerCase(),
    label: `Subscription ${subscriptionId.slice(0, 8)}…`,
    subscriptionId: subscriptionId.toLowerCase(),
    tenantId: tenantId.toLowerCase(),
  }),
  templates: [
    {
      key: 'storage-public-blob',
      title: (r) => `Storage account ${r.name} allows anonymous blob access`,
      severity: 'critical',
      category: 'Data Exposure',
      exposure: 'public',
      exploitability: 1.5,
      resource: (rng, account) => {
        const name = `st${rng.pick(BUCKET_PURPOSES).replace(/-/g, '').slice(0, 10)}${rng.alnum(4, 'abcdefghijklmnopqrstuvwxyz0123456789')}`;
        return { id: `/subscriptions/${account.subscriptionId}/storageAccounts/${name}`, name, type: 'Storage account', location: rng.pick(AZURE_REGIONS), container: rng.pick(['exports', 'backup', '$web', 'uploads']) };
      },
      explain: (r) =>
        `${r.name} (${r.location}) has "Allow Blob anonymous access" enabled and the container "${r.container}" is set to ` +
        `public access level "Container", so anyone can list and download every blob in it.`,
      impact: 'Public exposure of stored files and backups.',
      remediation: [
        'Set allowBlobPublicAccess to false on the storage account.',
        'Use SAS tokens with short expiry or private endpoints for sharing.',
        'Assign the Azure Policy "Storage account public access should be disallowed".',
      ],
      effort: '10 min',
      frameworks: ['CIS Azure 3.7', 'SOC 2 C1.1'],
    },
    {
      key: 'nsg-open-rdp',
      title: (r) => `NSG ${r.name} allows RDP from the internet`,
      severity: 'high',
      category: 'Network',
      exposure: 'public',
      exploitability: 1.2,
      count: [1, 2],
      resource: (rng, account) => {
        const name = `nsg-${rng.pick(['jumpbox', 'app', 'legacy', 'build'])}-${rng.pick(['prod', 'dev'])}`;
        return { id: `/subscriptions/${account.subscriptionId}/nsg/${name}`, name, type: 'Network security group', location: rng.pick(AZURE_REGIONS) };
      },
      explain: (r) =>
        `${r.name} has an inbound rule allowing TCP 3389 from "Any". Exposed RDP is among the most common initial access ` +
        `vectors for ransomware operators.`,
      impact: 'Brute-force and exploit exposure of Windows hosts.',
      remediation: [
        'Delete the inbound Any→3389 rule.',
        'Use Azure Bastion or just-in-time VM access for administration.',
      ],
      effort: '10 min',
      frameworks: ['CIS Azure 6.1', 'SOC 2 CC6.6'],
    },
    {
      key: 'guest-owner',
      title: (r) => `Guest user ${r.email} has Owner on the subscription`,
      severity: 'high',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.3,
      resource: (rng) => {
        const email = `${rng.pick(PEOPLE)}@${rng.pick(EXTERNAL_DOMAINS)}`;
        return { id: `guest-owner:${email}`, name: email, type: 'Role assignment', email };
      },
      explain: (r) =>
        `${r.email} is a B2B guest with the Owner role at subscription scope. Owners can grant themselves any access, ` +
        `read secrets and delete resources, and guests are outside your MFA and lifecycle controls.`,
      impact: 'Full control of cloud resources by an external identity.',
      remediation: [
        'Replace Owner with the narrowest role the guest needs, scoped to a resource group.',
        'Use PIM for time-bound elevation.',
        'Review guest access quarterly with Entra access reviews.',
      ],
      effort: '10 min',
      frameworks: ['CIS Azure 1.23', 'SOC 2 CC6.2'],
    },
    {
      key: 'sql-firewall-any',
      title: (r) => `SQL server ${r.name} firewall allows 0.0.0.0-255.255.255.255`,
      severity: 'high',
      category: 'Network',
      exposure: 'public',
      probability: 0.7,
      resource: (rng, account) => {
        const name = `sql-${rng.pick(['orders', 'crm', 'reporting'])}-${rng.alnum(4, 'abcdefghijklmnopqrstuvwxyz')}`;
        return { id: `/subscriptions/${account.subscriptionId}/sql/${name}`, name, type: 'Azure SQL server' };
      },
      explain: (r) => `${r.name} has a firewall rule covering the entire IPv4 range, exposing the database endpoint to the internet.`,
      impact: 'Database reachable for brute force from anywhere.',
      remediation: ['Remove the all-IP firewall rule.', 'Use private endpoints and Entra-only authentication.'],
      effort: '20 min',
      frameworks: ['CIS Azure 4.1.2', 'SOC 2 CC6.6'],
    },
    {
      key: 'keyvault-no-purge',
      title: (r) => `Key Vault ${r.name} has purge protection off`,
      severity: 'medium',
      category: 'Configuration',
      exposure: 'internal',
      resource: (rng, account) => {
        const name = `kv-${rng.pick(['payments', 'platform', 'shared'])}-${rng.pick(['prod', 'stg'])}`;
        return { id: `/subscriptions/${account.subscriptionId}/vaults/${name}`, name, type: 'Key Vault' };
      },
      explain: (r) =>
        `${r.name} can be permanently purged. An attacker or a mistake can destroy encryption keys and make encrypted data unrecoverable.`,
      impact: 'Irrecoverable loss of keys and the data they protect.',
      remediation: ['Enable soft delete and purge protection on the vault.'],
      effort: '2 min',
      frameworks: ['CIS Azure 8.5', 'ISO 27001 A.8.13'],
    },
    {
      key: 'defender-off',
      title: (r) => `Defender for Cloud plans disabled: ${r.plans.join(', ')}`,
      severity: 'medium',
      category: 'Logging',
      exposure: 'internal',
      resource: (rng, account) => {
        const plans = rng.sample(['Servers', 'Storage', 'Key Vault', 'SQL', 'Containers'], rng.int(2, 3));
        return { id: `${account.subscriptionId}:defender`, name: 'Defender for Cloud', type: 'Subscription setting', plans };
      },
      explain: (r) => `Threat detection is off for ${r.plans.join(', ')}. Suspicious activity on those resources will not raise alerts.`,
      impact: 'Reduced detection of active attacks.',
      remediation: ['Enable the listed Defender plans.', 'Route Defender alerts to your SIEM or on-call channel.'],
      effort: '10 min',
      frameworks: ['CIS Azure 2.1.1', 'SOC 2 CC7.2'],
    },
  ],
};
