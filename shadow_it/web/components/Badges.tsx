import type { DiscoveredApp, RiskBand } from "@/lib/api";

export function RiskBadge({ band, score }: { band: RiskBand; score: number }) {
  return (
    <span className={`badge ${band}`}>
      {band} · {score}
    </span>
  );
}

/**
 * The signals a reviewer triages on, in the order they should be read.
 *
 * These are the difference between "an app has Drive access" and "an app
 * nobody can vouch for has Drive access for everyone", so they belong in the
 * table rather than two clicks away on a detail page.
 */
export function AppFlags({ app }: { app: DiscoveredApp }) {
  const flags: string[] = [];
  if (app.is_anonymous) flags.push("unverified publisher");
  if (app.tenant_wide_consent) flags.push("tenant-wide");
  if (app.has_application_permissions) flags.push("app-only");
  if (app.admin_count > 0) flags.push(`${app.admin_count} admin`);
  if (app.is_native_app) flags.push("native");

  if (flags.length === 0) return <span className="muted">—</span>;
  return (
    <span className="flags">
      {flags.map((flag) => (
        <span key={flag} className="badge flag">
          {flag}
        </span>
      ))}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return <span className="badge plain">{status}</span>;
}
