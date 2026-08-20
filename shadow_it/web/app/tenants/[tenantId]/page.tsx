import Link from "next/link";
import { getSummary, listApps, type Scan } from "@/lib/api";
import { AppFlags, RiskBadge, StatusBadge } from "@/components/Badges";
import { ErrorPanel } from "@/components/ErrorPanel";
import { ScanButton } from "@/components/ScanButton";

export const dynamic = "force-dynamic";

type Search = Record<string, string | string[] | undefined>;

const one = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

export default async function TenantDashboard({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<Search>;
}) {
  const { tenantId } = await params;
  const search = await searchParams;

  const band = one(search.band);
  const status = one(search.status);
  const provider = one(search.provider);
  const q = one(search.q);

  // Only send filters the user actually set — the API treats a missing
  // parameter as "no filter", and an empty string as a bad value.
  const query = new URLSearchParams({ limit: "200" });
  if (band) query.set("band", band);
  if (status) query.set("status", status);
  if (provider) query.set("provider", provider);
  if (q) query.set("search", q);

  let summary, apps;
  try {
    [summary, { apps }] = await Promise.all([
      getSummary(tenantId),
      listApps(tenantId, query),
    ]);
  } catch (error) {
    return <ErrorPanel error={error} />;
  }

  const { counts } = summary;
  const filtered = Boolean(band || status || provider || q);

  return (
    <>
      <div className="row">
        <h2>Discovered apps</h2>
        <div className="spacer" />
        <ScanButton tenantId={tenantId} />
      </div>

      <div className="cards">
        <Stat label="Apps" value={counts.total_apps} />
        <Stat label="High risk" value={counts.high} tone="high" />
        <Stat label="Medium" value={counts.medium} tone="medium" />
        <Stat label="Low" value={counts.low} tone="low" />
        <Stat label="Unreviewed" value={counts.unreviewed} />
        <Stat label="Unverified publisher" value={counts.unverified_publisher} />
        <Stat label="Tenant-wide" value={counts.tenant_wide} />
        <Stat label="App-only" value={counts.app_only} />
      </div>

      <ScanBanner scans={summary.scans_by_provider} providers={summary.connected_providers} />

      <form className="filters" method="get">
        <select name="band" defaultValue={band} aria-label="Risk band">
          <option value="">All risk</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select name="status" defaultValue={status} aria-label="Review status">
          <option value="">All statuses</option>
          <option value="new">Unreviewed</option>
          <option value="approved">Approved</option>
          <option value="blocked">Blocked</option>
          <option value="ignored">Ignored</option>
        </select>
        <select name="provider" defaultValue={provider} aria-label="Provider">
          <option value="">All providers</option>
          <option value="google">Google Workspace</option>
          <option value="microsoft">Microsoft 365</option>
        </select>
        <input name="q" defaultValue={q} placeholder="Search app name…" aria-label="Search" />
        <button className="btn" type="submit">
          Filter
        </button>
        {filtered && (
          <Link className="btn" href={`/tenants/${tenantId}`}>
            Clear
          </Link>
        )}
      </form>

      {apps.length === 0 ? (
        <div className="empty">
          {filtered
            ? "No apps match those filters."
            : "No apps discovered yet. Connect a provider and run a scan."}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Application</th>
                <th>Provider</th>
                <th>Category</th>
                <th>Risk</th>
                <th className="num">Users</th>
                <th className="num">Scopes</th>
                <th>Signals</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {apps.map((app) => (
                <tr key={app.id}>
                  <td className="name">
                    <Link href={`/tenants/${tenantId}/apps/${app.id}`}>{app.display_name}</Link>
                    <span className="cid">{app.client_id}</span>
                  </td>
                  <td className="muted">
                    {app.provider === "google" ? "Workspace" : "Microsoft 365"}
                  </td>
                  <td className="muted">{app.category.replace(/_/g, " ")}</td>
                  <td>
                    <RiskBadge band={app.risk_band} score={app.risk_score} />
                  </td>
                  <td className="num">{app.user_count}</td>
                  <td className="num">{app.scopes.length}</td>
                  <td>
                    <AppFlags app={app} />
                  </td>
                  <td>
                    <StatusBadge status={app.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ fontSize: "0.82rem" }}>
        Showing {apps.length} app{apps.length === 1 ? "" : "s"}, worst first.
      </p>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`card ${tone ?? ""}`}>
      <div className="n">{value}</div>
      <div className="k">{label}</div>
    </div>
  );
}

function ScanBanner({ scans, providers }: { scans: Scan[]; providers: string[] }) {
  if (providers.length === 0 && scans.length === 0) {
    return (
      <div className="empty" style={{ marginBottom: "1rem" }}>
        No provider is connected. This deployment is running in demo mode, or the
        customer has not consented yet.
      </div>
    );
  }
  if (scans.length === 0) return null;

  return (
    <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
      {scans.map((scan) => (
        <span key={scan.id} style={{ marginRight: "1.25rem" }}>
          <strong>{scan.provider === "google" ? "Workspace" : "Microsoft 365"}</strong>:{" "}
          {scan.status}
          {scan.finished_at ? ` · ${new Date(scan.finished_at).toLocaleString()}` : " · running"}
          {" · "}
          {scan.apps_found} apps from {scan.users_scanned} users
          {scan.errors?.length ? ` · ${scan.errors.length} error(s)` : ""}
        </span>
      ))}
    </p>
  );
}
