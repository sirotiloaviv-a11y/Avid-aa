// Vocabulary the mock generators draw from so simulated resources look like
// a plausible mid-size company rather than "resource-1, resource-2".

export const PEOPLE = [
  'maya.cohen', 'daniel.levi', 'noa.friedman', 'eitan.shapiro', 'tamar.katz',
  'yonatan.mizrahi', 'shira.peretz', 'omer.biton', 'lior.azulay', 'adi.golan',
  'sarah.miller', 'james.chen', 'priya.nair', 'lucas.martin', 'emma.schmidt',
  'carlos.rivera', 'olivia.brown', 'ethan.walker', 'sofia.rossi', 'liam.oconnor',
];

export const EXTERNAL_DOMAINS = [
  'gmail.com', 'outlook.com', 'proton.me', 'yahoo.com', 'contractor-hub.io',
  'freelance-devs.net', 'agency-partners.co',
];

export const REPOS = [
  'payments-service', 'web-app', 'infra-terraform', 'mobile-ios', 'data-pipeline',
  'auth-gateway', 'billing-api', 'internal-tools', 'ml-models', 'customer-portal',
  'deploy-scripts', 'analytics-etl',
];

export const SECRET_TYPES = [
  { type: 'AWS Access Key ID', prefix: 'AKIA', file: 'config/production.env' },
  { type: 'Stripe Live Secret Key', prefix: 'sk_live_', file: 'src/billing/client.ts' },
  { type: 'Slack Bot Token', prefix: 'xoxb-', file: 'scripts/notify.py' },
  { type: 'GCP Service Account Key', prefix: '"private_key_id": "', file: 'deploy/gcp-sa.json' },
  { type: 'PostgreSQL Connection String', prefix: 'postgres://admin:', file: 'docker-compose.override.yml' },
];

export const BUCKET_PURPOSES = [
  'customer-exports', 'backups', 'invoices', 'logs-archive', 'ml-training-data',
  'marketing-assets', 'data-lake-raw', 'user-uploads',
];

export const AWS_REGIONS = ['us-east-1', 'us-west-2', 'eu-west-1', 'eu-central-1', 'ap-southeast-1'];
export const AZURE_REGIONS = ['eastus', 'westeurope', 'northeurope', 'westus2', 'israelcentral'];

export const SENSITIVE_DOCS = [
  'Q3 Board Deck - Financials', 'Employee Salaries 2026', 'Customer List (Master)',
  'M&A Target Analysis', 'Production Credentials Backup', 'Payroll Export',
  'Security Incident Postmortem', 'Investor Cap Table',
];

export const SLACK_CHANNELS = [
  'finance', 'legal-private', 'eng-incidents', 'hr-confidential', 'sales-deals',
  'exec-team', 'security-ops', 'customer-escalations',
];

export const OAUTH_APPS = [
  { name: 'PDF Converter Pro', publisher: 'Unverified publisher' },
  { name: 'Calendar Sync Plus', publisher: 'Unverified publisher' },
  { name: 'MailMerge Wizard', publisher: 'Unverified publisher' },
  { name: 'AI Notes Assistant', publisher: 'notes-ai.app' },
  { name: 'Drive Backup Tool', publisher: 'Unverified publisher' },
];
