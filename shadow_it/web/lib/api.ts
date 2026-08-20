/**
 * Server-side API client.
 *
 * Every call in here runs on the Next.js server, never in the browser. That is
 * deliberate: API_KEY is an operator key that can read every tenant, so it must
 * never be exposed as a NEXT_PUBLIC_ variable or reach client JavaScript. The
 * browser talks only to this app; this app talks to the API.
 *
 * A pleasant side effect: no CORS configuration is needed anywhere.
 */

const API_URL = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const API_KEY = process.env.API_KEY ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (!API_KEY) {
    throw new ApiError("API_KEY is not set for the dashboard process.", 500);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${API_KEY}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      // Inventory data changes on every scan; a cached table is a wrong table.
      cache: "no-store",
    });
  } catch (cause) {
    // Almost always "the api container is not up yet" during a cold start.
    throw new ApiError(`Cannot reach the API at ${API_URL}: ${String(cause)}`, 503);
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(
      `${method} ${path} failed (${response.status}): ${detail.slice(0, 300)}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

/* ------------------------------------------------------------------ types */
/* Mirrors the FastAPI responses. Kept hand-written and small rather than
   generated: the dashboard reads a handful of fields, and a generated client
   would be more machinery than the whole frontend. */

export type RiskBand = "high" | "medium" | "low";
export type AppStatus = "new" | "approved" | "blocked" | "ignored";
export type ProviderName = "google" | "microsoft";

export interface Tenant {
  id: string;
  name: string;
  primary_domain: string;
  plan: string;
  is_active: boolean;
  directory_size: number;
}

export interface DiscoveredApp {
  id: string;
  provider: ProviderName;
  client_id: string;
  display_name: string;
  category: string;
  risk_score: number;
  risk_band: RiskBand;
  risk_reasons: string[];
  capabilities: string[];
  scopes: string[];
  user_count: number;
  admin_count: number;
  is_anonymous: boolean;
  is_native_app: boolean;
  tenant_wide_consent: boolean;
  has_application_permissions: boolean;
  status: AppStatus;
  first_seen_at: string;
  last_seen_at: string;
}

export interface AppGrantRow {
  user_email: string;
  grant_type: "delegated" | "tenant_wide" | "application";
  scopes: string[];
  first_seen_at: string;
  revoked_at: string | null;
}

export interface AppDetail extends DiscoveredApp {
  grants: AppGrantRow[] | null;
  reviewed_by: string;
  reviewed_at: string | null;
}

export interface Scan {
  id: string;
  provider: ProviderName;
  status: "running" | "success" | "partial" | "failed";
  trigger_kind: string;
  users_scanned: number;
  grants_found: number;
  apps_found: number;
  new_apps: number;
  errors: string[];
  started_at: string;
  finished_at: string | null;
}

export interface Summary {
  counts: {
    total_apps: number;
    high: number;
    medium: number;
    low: number;
    unreviewed: number;
    unverified_publisher: number;
    tenant_wide: number;
    app_only: number;
  };
  connected_providers: ProviderName[];
  scans_by_provider: Scan[];
}

/* ---------------------------------------------------------------- queries */

export const listTenants = () => api.get<{ tenants: Tenant[] }>("/v1/tenants");

export const getSummary = (tenantId: string) =>
  api.get<Summary>(`/v1/tenants/${tenantId}/summary`);

export const listApps = (tenantId: string, query: URLSearchParams) =>
  api.get<{ apps: DiscoveredApp[]; count: number }>(
    `/v1/tenants/${tenantId}/apps?${query.toString()}`,
  );

export const getApp = (tenantId: string, appId: string) =>
  api.get<AppDetail>(`/v1/tenants/${tenantId}/apps/${appId}`);

export const getProviders = () =>
  api.get<{ providers: ProviderName[] }>("/v1/connect/providers");
