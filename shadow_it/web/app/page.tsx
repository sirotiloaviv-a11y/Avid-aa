import Link from "next/link";
import { listTenants } from "@/lib/api";
import { ErrorPanel } from "@/components/ErrorPanel";

export const dynamic = "force-dynamic";

export default async function TenantsPage() {
  let tenants;
  try {
    ({ tenants } = await listTenants());
  } catch (error) {
    return <ErrorPanel error={error} />;
  }

  return (
    <>
      <h2>Tenants</h2>
      <p className="lede">Pick a customer to see their third-party app inventory.</p>

      {tenants.length === 0 ? (
        <div className="empty">
          <p>No tenants yet.</p>
          <p>
            Create one through the API, or seed the local demo data:
            <br />
            <code>docker compose exec api python -m app.main --seed-demo</code>
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Domain</th>
                <th>Plan</th>
                <th className="num">Directory</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id}>
                  <td className="name">
                    <Link href={`/tenants/${tenant.id}`}>{tenant.name}</Link>
                  </td>
                  <td className="muted">{tenant.primary_domain}</td>
                  <td>
                    <span className="badge plain">{tenant.plan}</span>
                  </td>
                  <td className="num">{tenant.directory_size || "—"}</td>
                  <td className="muted">{tenant.is_active ? "active" : "inactive"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
