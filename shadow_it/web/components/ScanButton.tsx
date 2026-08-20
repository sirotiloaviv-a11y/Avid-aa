"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

/**
 * Starts a scan and refreshes the page data.
 *
 * The POST goes to this app's own route handler, not to the API: the operator
 * key lives on the server and must not be handed to the browser.
 *
 * The API returns 202 immediately — a full Workspace scan is minutes of work —
 * so this reports "started" and refreshes; the scan banner picks up progress.
 */
export function ScanButton({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenantId }),
      });
      const body = await response.json();
      if (!response.ok) {
        setMessage(body.error ?? "Could not start the scan.");
      } else {
        setMessage(`Scan started (${(body.providers ?? []).join(", ") || "all providers"}).`);
        startTransition(() => router.refresh());
      }
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="row">
      <button className="btn primary" onClick={run} disabled={busy || pending}>
        {busy ? "Starting…" : "Run scan"}
      </button>
      {message && <span className="muted">{message}</span>}
    </span>
  );
}
