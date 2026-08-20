import Link from "next/link";
import { getApp } from "@/lib/api";
import { AppFlags, RiskBadge, StatusBadge } from "@/components/Badges";
import { ErrorPanel } from "@/components/ErrorPanel";

export const dynamic = "force-dynamic";

const GRANT_LABELS: Record<string, string> = {
  delegated: "user consent",
  tenant_wide: "admin consent, whole directory",
  application: "app-only, no user",
};

export default async function AppDetail({
  params,
}: {
  params: Promise<{ tenantId: string; appId: string }>;
}) {
  const { tenantId, appId } = await params;

  let app;
  try {
    app = await getApp(tenantId, appId);
  } catch (error) {
    return <ErrorPanel error={error} />;
  }

  const grants = app.grants ?? [];

  return (
    <>
      <p className="back">
        <Link href={`/tenants/${tenantId}`}>← Back to inventory</Link>
      </p>

      <div className="row">
        <h2 style={{ margin: 0 }}>{app.display_name}</h2>
        <RiskBadge band={app.risk_band} score={app.risk_score} />
        <StatusBadge status={app.status} />
      </div>
      <p className="lede scopes">{app.client_id}</p>

      <div className="cards">
        <Stat label="Users" value={String(app.user_count)} />
        <Stat label="Admin grants" value={String(app.admin_count)} />
        <Stat label="Scopes" value={String(app.scopes.length)} />
        <Stat
          label="Provider"
          value={app.provider === "google" ? "Workspace" : "Microsoft 365"}
        />
      </div>

      <div className="row" style={{ marginBottom: "1rem" }}>
        <AppFlags app={app} />
      </div>

      {/* The reasons are the product: a band with no explanation gets ignored
          by the third week, so they are shown before the raw scope list. */}
      <h2>Why this score</h2>
      <div className="card">
        <ul className="reasons">
          {app.risk_reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      </div>

      {app.capabilities.length > 0 && (
        <>
          <h2>What it can do</h2>
          <div className="card">
            <ul className="reasons">
              {app.capabilities.map((capability) => (
                <li key={capability}>{capability}</li>
              ))}
            </ul>
          </div>
        </>
      )}

      <h2>Granted scopes</h2>
      <div className="card scopes">
        {app.scopes.map((scope) => (
          <div key={scope}>{scope}</div>
        ))}
      </div>

      <h2>Who granted it</h2>
      {grants.length === 0 ? (
        <div className="empty">No grant records.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Principal</th>
                <th>Grant type</th>
                <th className="num">Scopes</th>
                <th>First seen</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {grants.map((grant) => (
                <tr key={`${grant.user_email}-${grant.grant_type}`}>
                  <td className="name">{grant.user_email}</td>
                  <td className="muted">
                    {GRANT_LABELS[grant.grant_type] ?? grant.grant_type}
                  </td>
                  <td className="num">{grant.scopes.length}</td>
                  <td className="muted">
                    {new Date(grant.first_seen_at).toLocaleDateString()}
                  </td>
                  <td>
                    <span className="badge plain">
                      {grant.revoked_at ? "revoked" : "active"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="n" style={{ fontSize: "1.15rem" }}>
        {value}
      </div>
      <div className="k">{label}</div>
    </div>
  );
}
