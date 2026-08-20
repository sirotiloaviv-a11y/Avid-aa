import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";

/**
 * Proxy for the scan button.
 *
 * Exists so the browser never sees the operator API key. It also pins the
 * shape of what a client can ask for: a tenant id and nothing else — no
 * arbitrary path, no forwarded headers.
 */
export async function POST(request: Request) {
  let tenantId: unknown;
  try {
    ({ tenantId } = await request.json());
  } catch {
    return NextResponse.json({ error: "Expected a JSON body." }, { status: 400 });
  }

  if (typeof tenantId !== "string" || !/^[0-9a-fA-F-]{36}$/.test(tenantId)) {
    return NextResponse.json({ error: "tenantId must be a UUID." }, { status: 400 });
  }

  try {
    const result = await api.post<{ status: string; providers: string[] }>(
      `/v1/tenants/${tenantId}/scans`,
    );
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Scan failed to start." },
      { status },
    );
  }
}
