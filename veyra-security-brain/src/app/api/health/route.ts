import { NextResponse } from "next/server";

/**
 * Liveness probe.
 *
 * Reports only that the Node process is up and serving. It deliberately does
 * not touch the database: a liveness check that fails on a transient database
 * blip causes orchestrators to restart a perfectly healthy process. A separate
 * readiness endpoint that does check dependencies belongs with the first
 * deployment work.
 *
 * The response carries no version, hostname or build metadata — an unauthenticated
 * endpoint should not describe the deployment to whoever asks.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    { status: "ok", timestamp: new Date().toISOString() },
    { headers: { "Cache-Control": "no-store" } },
  );
}
