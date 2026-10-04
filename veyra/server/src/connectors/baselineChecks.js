// Checks each connector evaluates that pass in the demo tenant. A real scan
// runs many more checks than it fails; compliance readiness is measured over
// all of them, not just the failing ones.

export const BASELINE_CHECKS = {
  'google-workspace': [
    { key: 'gw-sso-saml', title: 'SAML SSO configured for third-party apps', category: 'Identity', frameworks: ['SOC 2 CC6.1', 'ISO 27001 A.8.5'] },
    { key: 'gw-password-policy', title: 'Password length and strength enforced', category: 'Identity', frameworks: ['ISO 27001 A.5.17'] },
    { key: 'gw-audit-export', title: 'Admin and login audit logs exported to BigQuery', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
    { key: 'gw-dlp-rules', title: 'Drive DLP rules for payment card data', category: 'Data Exposure', frameworks: ['ISO 27001 A.8.12'] },
    { key: 'gw-mobile-mgmt', title: 'Advanced mobile management enabled', category: 'Configuration', frameworks: ['ISO 27001 A.8.9'] },
  ],
  'microsoft-365': [
    { key: 'm365-safe-links', title: 'Defender Safe Links and Safe Attachments enabled', category: 'Configuration', frameworks: ['SOC 2 CC7.1'] },
    { key: 'm365-dkim-dmarc', title: 'DKIM signing and DMARC enforcement on all domains', category: 'Configuration', frameworks: ['ISO 27001 A.8.9'] },
    { key: 'm365-unified-audit', title: 'Unified audit log enabled', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
    { key: 'm365-guest-review', title: 'Quarterly access reviews for guests', category: 'Identity', frameworks: ['SOC 2 CC6.2', 'ISO 27001 A.5.18'] },
    { key: 'm365-sensitivity-labels', title: 'Sensitivity labels published', category: 'Data Exposure', frameworks: ['SOC 2 C1.1', 'ISO 27001 A.8.12'] },
  ],
  aws: [
    { key: 'aws-guardduty', title: 'GuardDuty enabled in all regions', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.16'] },
    { key: 'aws-iam-password-policy', title: 'IAM password policy meets CIS requirements', category: 'Identity', frameworks: ['ISO 27001 A.5.17'] },
    { key: 'aws-kms-rotation', title: 'KMS customer keys rotated annually', category: 'Secrets', frameworks: ['ISO 27001 A.8.24'] },
    { key: 'aws-backup-plan', title: 'AWS Backup plan covers production databases', category: 'Configuration', frameworks: ['ISO 27001 A.8.13'] },
    { key: 'aws-config-recorder', title: 'AWS Config recording all resources', category: 'Configuration', frameworks: ['SOC 2 CC8.1', 'ISO 27001 A.8.9'] },
    { key: 'aws-vpc-flow-logs', title: 'VPC flow logs enabled', category: 'Network', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
  ],
  azure: [
    { key: 'az-activity-log', title: 'Activity log exported to Log Analytics', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
    { key: 'az-storage-https', title: 'Secure transfer required on storage accounts', category: 'Data Exposure', frameworks: ['SOC 2 CC6.7', 'ISO 27001 A.8.24'] },
    { key: 'az-policy-baseline', title: 'Azure Security Benchmark initiative assigned', category: 'Configuration', frameworks: ['SOC 2 CC7.1', 'ISO 27001 A.8.9'] },
    { key: 'az-pim', title: 'Privileged Identity Management for subscription roles', category: 'Identity', frameworks: ['SOC 2 CC6.3', 'ISO 27001 A.5.15'] },
    { key: 'az-backup-vault', title: 'Recovery Services vault protects production VMs', category: 'Configuration', frameworks: ['ISO 27001 A.8.13'] },
  ],
  github: [
    { key: 'gh-secret-scanning', title: 'Secret scanning enabled on all repositories', category: 'Secrets', frameworks: ['SOC 2 CC6.1', 'ISO 27001 A.8.24'] },
    { key: 'gh-audit-stream', title: 'Audit log streaming to SIEM', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
    { key: 'gh-actions-allowlist', title: 'Actions restricted to verified creators', category: 'Third-Party', frameworks: ['SOC 2 CC9.2', 'ISO 27001 A.5.19'] },
    { key: 'gh-code-scanning', title: 'Code scanning on default branches', category: 'Vulnerabilities', frameworks: ['SOC 2 CC7.1', 'ISO 27001 A.8.8'] },
    { key: 'gh-base-permissions', title: 'Organization base permission set to read', category: 'Identity', frameworks: ['SOC 2 CC6.3', 'ISO 27001 A.5.15'] },
  ],
  slack: [
    { key: 'sl-sso', title: 'Session duration limited to 7 days', category: 'Identity', frameworks: ['ISO 27001 A.8.5'] },
    { key: 'sl-audit-logs', title: 'Audit logs API connected', category: 'Logging', frameworks: ['SOC 2 CC7.2', 'ISO 27001 A.8.15'] },
    { key: 'sl-dlp', title: 'DLP scanning for credentials in messages', category: 'Data Exposure', frameworks: ['ISO 27001 A.8.12'] },
    { key: 'sl-ekm', title: 'Workspace export restricted to owners', category: 'Data Exposure', frameworks: ['SOC 2 C1.1', 'ISO 27001 A.5.33'] },
  ],
};
