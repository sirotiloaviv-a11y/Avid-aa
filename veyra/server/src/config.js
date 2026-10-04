import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

const int = (value, fallback) => {
  const parsed = Number.parseInt(value ?? '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  port: int(process.env.PORT, 4000),
  // Loopback by default: the prototype has no authentication.
  host: process.env.HOST ?? '127.0.0.1',
  connectorLatencyMs: int(process.env.VEYRA_CONNECTOR_LATENCY_MS, 900),
  remediationDelayMs: int(process.env.VEYRA_REMEDIATION_DELAY_MS, 2500),
  staticDir: path.resolve(here, '../../web/dist'),
};

/** Accounts connected on startup so the dashboard has data immediately. */
export const DEMO_CONNECTIONS = {
  'google-workspace': { domain: 'acme.com', adminEmail: 'it-admin@acme.com' },
  aws: { roleArn: 'arn:aws:iam::482910375516:role/VeyraSecurityAudit', externalId: 'veyra-7f3a91' },
  github: { organization: 'acme-corp' },
  slack: { workspace: 'acme' },
};
