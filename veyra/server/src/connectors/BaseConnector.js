import { generateFindings } from '../mock/generateFindings.js';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Common contract every integration implements. A production connector would
 * override `authenticate` and `collect` with real API calls (OAuth exchange,
 * STS AssumeRole, Graph API, ...). In this prototype every provider runs in
 * mock mode: `authenticate` validates the identifiers the user typed and
 * `collect` returns simulated findings from the provider's templates.
 *
 * Connectors only ever ask for identifiers (tenant IDs, role ARNs, org
 * names), never for raw secrets: access is granted through the provider's
 * own consent flow, which is how a read-only posture tool should work.
 */
export class BaseConnector {
  constructor(definition, { latencyMs = 0 } = {}) {
    const required = ['id', 'name', 'shortName', 'vendor', 'description', 'credentialFields', 'templates', 'accountFrom'];
    for (const key of required) {
      if (definition[key] === undefined) throw new Error(`Connector definition is missing "${key}"`);
    }
    this.definition = definition;
    this.latencyMs = latencyMs;
  }

  get id() { return this.definition.id; }
  get name() { return this.definition.name; }
  get templates() { return this.definition.templates; }

  /** Public metadata safe to send to the browser. */
  describe() {
    const { id, name, shortName, vendor, description, color, authMethod, scopes, credentialFields, docsUrl } = this.definition;
    return {
      id, name, shortName, vendor, description, color, authMethod, docsUrl,
      scopes: scopes ?? [],
      credentialFields: credentialFields.map(({ pattern, ...field }) => ({
        ...field,
        pattern: pattern ? pattern.source : undefined,
        patternFlags: pattern ? pattern.flags : undefined,
      })),
      checks: this.definition.templates.length,
    };
  }

  /** Returns `{ ok, errors }`, where errors maps a field name to a message. */
  validateCredentials(input) {
    const errors = {};
    const values = {};
    for (const field of this.definition.credentialFields) {
      const raw = input?.[field.name];
      const value = typeof raw === 'string' ? raw.trim() : '';
      if (!value) {
        if (field.required !== false) errors[field.name] = `${field.label} is required`;
        continue;
      }
      if (value.length > 256) {
        errors[field.name] = `${field.label} is too long`;
      } else if (field.pattern && !field.pattern.test(value)) {
        errors[field.name] = field.patternMessage ?? `${field.label} has an invalid format`;
      } else {
        values[field.name] = value;
      }
    }
    return { ok: Object.keys(errors).length === 0, errors, values };
  }

  /** Simulates the consent / token exchange and returns the account profile. */
  async authenticate(credentials, { simulateLatency = true } = {}) {
    const result = this.validateCredentials(credentials);
    if (!result.ok) {
      const error = new Error('Invalid connection details');
      error.status = 400;
      error.fields = result.errors;
      throw error;
    }
    if (simulateLatency && this.latencyMs) await sleep(this.latencyMs);
    return this.definition.accountFrom(result.values);
  }

  /** Runs one posture scan against the connected account. */
  async collect(account, { scanNumber = 0, now = Date.now(), simulateLatency = true } = {}) {
    if (simulateLatency && this.latencyMs) await sleep(this.latencyMs);
    return generateFindings(
      { id: this.id, templates: this.templates, accountKey: (a) => a.key },
      { account, scanNumber, now },
    );
  }
}
