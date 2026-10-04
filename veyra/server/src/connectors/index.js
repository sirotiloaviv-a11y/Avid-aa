import { BaseConnector } from './BaseConnector.js';
import googleWorkspace from './providers/googleWorkspace.js';
import microsoft365 from './providers/microsoft365.js';
import aws from './providers/aws.js';
import azure from './providers/azure.js';
import github from './providers/github.js';
import slack from './providers/slack.js';

export const PROVIDER_DEFINITIONS = [googleWorkspace, microsoft365, aws, azure, github, slack];

/** Build the connector registry. `latencyMs` simulates API round-trips. */
export function createConnectors({ latencyMs = 0 } = {}) {
  const connectors = new Map();
  for (const definition of PROVIDER_DEFINITIONS) {
    connectors.set(definition.id, new BaseConnector(definition, { latencyMs }));
  }
  return connectors;
}
