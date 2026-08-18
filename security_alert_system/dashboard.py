"""A small read-only status dashboard served over HTTP.

Deliberately dependency-free: it uses ``asyncio.start_server`` and speaks just
enough HTTP/1.1 to serve three routes. That keeps the alerting service free of
a web framework it would otherwise only use for a status page.

    GET /             the dashboard (HTML, auto-refreshing)
    GET /api/status   the same data as JSON
    GET /healthz      "ok" — for a container healthcheck

SECURITY
--------
This page exposes what your monitor is watching and what it has matched. It
binds to ``127.0.0.1`` by default, which in a cloud container means "reachable
only from inside the container" — use ``docker exec``, an SSH tunnel, or your
platform's port-forward to view it.

Set ``DASHBOARD_HOST=0.0.0.0`` only together with ``DASHBOARD_TOKEN``, and
preferably behind a reverse proxy that terminates TLS. Without a token, anyone
who can reach the port can read your alert history. There are no write routes,
so the worst case is disclosure, not control.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

from .monitoring import Runtime

if TYPE_CHECKING:
    from .ingest import IngestPipeline

log = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 16 * 1024
MAX_INGEST_BYTES = 256 * 1024
READ_TIMEOUT_SECONDS = 10


class DashboardServer:
    def __init__(
        self,
        runtime: Runtime,
        host: str = "127.0.0.1",
        port: int = 8080,
        token: str = "",
        context: dict[str, Any] | None = None,
        ingest: "IngestPipeline | None" = None,
        ingest_token: str = "",
    ):
        self._runtime = runtime
        self._host = host
        self._port = port
        self._token = token
        # Static facts about the running config (keywords, feeds, cameras).
        self._context = context or {}
        self._ingest = ingest
        # Deliberately a separate secret from the dashboard token: a read
        # token handed to someone to look at the page must not also let
        # them inject alerts.
        self._ingest_token = ingest_token

    async def run(self, stop: asyncio.Event) -> None:
        try:
            server = await asyncio.start_server(self._handle, self._host, self._port)
        except OSError as exc:
            log.error("Dashboard could not bind %s:%d — %s", self._host, self._port, exc)
            return

        bound = ", ".join(str(s.getsockname()) for s in server.sockets or [])
        log.info("Dashboard listening on %s (token %s).",
                 bound, "required" if self._token else "NOT set")
        if self._host not in {"127.0.0.1", "localhost", "::1"} and not self._token:
            log.warning(
                "Dashboard is bound to %s with no DASHBOARD_TOKEN — the alert "
                "history is readable by anyone who can reach this port.", self._host,
            )

        async with server:
            await stop.wait()
        log.info("Dashboard stopped.")

    # ----------------------------------------------------------- plumbing
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=READ_TIMEOUT_SECONDS
            )
            if not request_line:
                return

            parts = request_line.decode("latin-1", "replace").split()
            if len(parts) < 2:
                await self._respond(writer, 400, "text/plain; charset=utf-8", b"bad request")
                return
            method, target = parts[0].upper(), parts[1]

            headers = await self._read_headers(reader)
            split = urlsplit(target)
            path = split.path.rstrip("/") or "/"
            query = parse_qs(split.query)

            if method == "POST":
                await self._handle_ingest(reader, writer, headers, path)
                return
            if method not in {"GET", "HEAD"}:
                await self._respond(writer, 405, "text/plain; charset=utf-8", b"method not allowed")
                return

            if path == "/healthz":
                await self._respond(writer, 200, "text/plain; charset=utf-8", b"ok")
                return

            if not self._authorised(headers, query):
                await self._respond(
                    writer, 401, "text/plain; charset=utf-8", "unauthorised".encode()
                )
                return

            if path == "/api/status":
                payload = {**self._runtime.snapshot(), "config": self._context}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                await self._respond(writer, 200, "application/json; charset=utf-8", body)
            elif path == "/":
                body = render_page(self._token_query()).encode("utf-8")
                await self._respond(writer, 200, "text/html; charset=utf-8", body)
            else:
                await self._respond(writer, 404, "text/plain; charset=utf-8", b"not found")

        except (asyncio.TimeoutError, ConnectionError):
            pass
        except Exception:  # noqa: BLE001 - a bad request must not kill the server
            log.exception("Dashboard request failed.")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

    async def _handle_ingest(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        path: str,
    ) -> None:
        """The one write route. Auth here is unconditional — unlike the read
        routes, there is no "no token configured" path that falls open."""
        if path != "/ingest":
            await self._respond(writer, 404, "text/plain; charset=utf-8", b"not found")
            return
        if self._ingest is None or not self._ingest_token:
            await self._respond(
                writer, 503, "application/json; charset=utf-8",
                b'{"error":"ingest is not configured"}',
            )
            return

        supplied = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not hmac.compare_digest(supplied, self._ingest_token):
            await self._respond(
                writer, 401, "application/json; charset=utf-8",
                b'{"error":"unauthorised"}',
            )
            return

        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_INGEST_BYTES:
            await self._respond(
                writer, 413, "application/json; charset=utf-8",
                b'{"error":"missing or oversized body"}',
            )
            return

        try:
            raw = await asyncio.wait_for(
                reader.readexactly(length), timeout=READ_TIMEOUT_SECONDS
            )
            payload = json.loads(raw.decode("utf-8"))
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ValueError,
                UnicodeDecodeError):
            await self._respond(
                writer, 400, "application/json; charset=utf-8",
                b'{"error":"body is not valid JSON"}',
            )
            return

        if not isinstance(payload, dict):
            await self._respond(
                writer, 400, "application/json; charset=utf-8",
                b'{"error":"body must be a JSON object"}',
            )
            return

        try:
            result = await self._ingest.submit(
                source=str(payload.get("source", "")),
                text=str(payload.get("text", "")),
                url=payload.get("url") or None,
                kind=str(payload.get("kind") or "external"),
                external_id=payload.get("id") or None,
                timestamp=_as_float(payload.get("timestamp")),
            )
        except Exception:  # noqa: BLE001 - a bad push must not kill the server
            log.exception("Ingest failed.")
            await self._respond(
                writer, 500, "application/json; charset=utf-8",
                b'{"error":"ingest failed"}',
            )
            return

        body = json.dumps(result.to_dict(), ensure_ascii=False).encode("utf-8")
        await self._respond(
            writer, 200 if result.accepted else 400,
            "application/json; charset=utf-8", body,
        )

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        total = 0
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_SECONDS)
            total += len(line)
            if not line or line in (b"\r\n", b"\n") or total > MAX_REQUEST_BYTES:
                break
            name, _, value = line.decode("latin-1", "replace").partition(":")
            headers[name.strip().lower()] = value.strip()
        return headers

    def _authorised(self, headers: dict[str, str], query: dict[str, list[str]]) -> bool:
        if not self._token:
            return True
        supplied = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        elif query.get("token"):
            supplied = query["token"][0]
        return hmac.compare_digest(supplied, self._token)

    def _token_query(self) -> str:
        """Propagate the token to the page's own fetch calls."""
        return f"?token={self._token}" if self._token else ""

    @staticmethod
    async def _respond(
        writer: asyncio.StreamWriter, status: int, content_type: str, body: bytes
    ) -> None:
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                  404: "Not Found", 405: "Method Not Allowed",
                  413: "Payload Too Large", 500: "Internal Server Error",
                  503: "Service Unavailable"}.get(status, "OK")
        stamp = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Date: {stamp}\r\n"
            "Cache-Control: no-store\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "Referrer-Policy: no-referrer\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(head + body)
        await writer.drain()


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def render_page(token_query: str = "") -> str:
    """The dashboard shell. Data is fetched client-side from /api/status."""
    return _PAGE.replace("__TOKEN_QUERY__", token_query)


_PAGE = """<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>מערכת התראות — סטטוס</title>
<style>
  :root {
    --bg:#f6f7f9; --panel:#fff; --border:#e2e5ea; --text:#14181f;
    --muted:#5f6773; --ok:#15803d; --degraded:#b45309; --down:#b91c1c;
    --crit:#b91c1c; --high:#c2410c; --elev:#a16207; --info:#3f6212;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:#0f1216; --panel:#171b21; --border:#282e37; --text:#e8ecf1;
      --muted:#98a2b0; --ok:#4ade80; --degraded:#fbbf24; --down:#f87171;
      --crit:#f87171; --high:#fb923c; --elev:#fbbf24; --info:#a3e635;
    }
  }
  * { box-sizing:border-box; }
  body {
    margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--text);
    font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif; line-height:1.5;
  }
  .wrap { max-width:1080px; margin:0 auto; }
  header { display:flex; flex-wrap:wrap; gap:12px; align-items:baseline;
           justify-content:space-between; margin-bottom:20px; }
  h1 { font-size:1.4rem; margin:0; letter-spacing:-.01em; }
  .stamp { color:var(--muted); font-size:.85rem; font-variant-numeric:tabular-nums; }
  .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          margin-bottom:24px; }
  .tile { background:var(--panel); border:1px solid var(--border); border-radius:10px;
          padding:14px 16px; }
  .tile .label { color:var(--muted); font-size:.78rem; margin-bottom:6px; }
  .tile .value { font-size:1.6rem; font-weight:650; font-variant-numeric:tabular-nums; }
  h2 { font-size:1rem; margin:26px 0 10px; color:var(--muted); font-weight:600; }
  .panel { background:var(--panel); border:1px solid var(--border);
           border-radius:10px; overflow:hidden; }
  .scroll { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-size:.9rem; }
  th, td { text-align:right; padding:9px 14px; border-bottom:1px solid var(--border);
           vertical-align:top; }
  th { color:var(--muted); font-weight:600; font-size:.78rem; white-space:nowrap; }
  tr:last-child td { border-bottom:none; }
  td.num { font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--muted); }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-inline-end:7px; }
  .s-ok{background:var(--ok)} .s-degraded{background:var(--degraded)}
  .s-down{background:var(--down)} .s-pending{background:var(--muted)}
  .badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:.75rem;
           font-weight:600; border:1px solid currentColor; white-space:nowrap; }
  .b-CRITICAL{color:var(--crit)} .b-HIGH{color:var(--high)}
  .b-ELEVATED{color:var(--elev)} .b-INFO{color:var(--info)}
  .chips { display:flex; flex-wrap:wrap; gap:5px; }
  .chip { background:var(--bg); border:1px solid var(--border); border-radius:6px;
          padding:1px 7px; font-size:.78rem; }
  a { color:inherit; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .empty { padding:26px 16px; text-align:center; color:var(--muted); }
  .err { color:var(--down); font-size:.8rem; }
  footer { margin-top:28px; color:var(--muted); font-size:.8rem; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🛡️ מערכת התראות ביטחוניות</h1>
    <div class="stamp" id="stamp">טוען…</div>
  </header>

  <div class="grid" id="tiles"></div>

  <h2>מקורות</h2>
  <div class="panel scroll"><table>
    <thead><tr>
      <th>מקור</th><th>סוג</th><th>מצב</th><th>עדכון אחרון</th>
      <th>פריטים</th><th>התראות</th><th>שגיאה אחרונה</th>
    </tr></thead>
    <tbody id="sources"></tbody>
  </table></div>

  <h2>התראות אחרונות</h2>
  <div class="panel scroll"><table>
    <thead><tr>
      <th>זמן</th><th>חומרה</th><th>מקור</th><th>כותרת</th><th>מילות מפתח</th>
    </tr></thead>
    <tbody id="alerts"></tbody>
  </table></div>

  <footer id="config"></footer>
</div>

<script>
const TOKEN_QUERY = "__TOKEN_QUERY__";
const SEV_HE = {CRITICAL:"קריטית", HIGH:"גבוהה", ELEVATED:"מוגברת", INFO:"מידע"};
const STATUS_HE = {ok:"תקין", degraded:"בעיה", down:"מושבת", pending:"ממתין"};

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function ago(ts) {
  if (!ts) return "—";
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if (s < 60) return `לפני ${s} שנ׳`;
  if (s < 3600) return `לפני ${Math.floor(s/60)} דק׳`;
  if (s < 86400) return `לפני ${Math.floor(s/3600)} שע׳`;
  return `לפני ${Math.floor(s/86400)} ימים`;
}
function uptime(sec) {
  const d = Math.floor(sec/86400), h = Math.floor(sec%86400/3600), m = Math.floor(sec%3600/60);
  return d ? `${d} י׳ ${h}ש׳` : h ? `${h}ש׳ ${m}ד׳` : `${m} דק׳`;
}
function clock(ts) {
  return new Date(ts*1000).toLocaleString("he-IL",
    {day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit"});
}

function render(d) {
  // Anything not fully "ok" is not counted as healthy — a degraded source is
  // one bad poll away from silently missing an alert.
  const healthy = d.sources.filter(s => s.status === "ok").length;
  const tiles = [
    ["התראות שנשלחו", d.alerts_sent],
    ["כשלי שליחה", d.alerts_failed],
    ["מקורות תקינים", `${healthy}/${d.sources.length}`],
    ["התראה אחרונה", ago(d.last_alert_at)],
    ["זמן פעילות", uptime(d.uptime_seconds)],
  ];
  document.getElementById("tiles").innerHTML = tiles.map(([l, v]) =>
    `<div class="tile"><div class="label">${esc(l)}</div>
     <div class="value">${esc(v)}</div></div>`).join("");

  document.getElementById("sources").innerHTML = d.sources.length ? d.sources.map(s => `
    <tr>
      <td>${esc(s.name)}</td>
      <td class="num">${esc(s.kind)}</td>
      <td><span class="dot s-${esc(s.status)}"></span>${esc(STATUS_HE[s.status] || s.status)}</td>
      <td class="num">${esc(ago(s.last_success))}</td>
      <td class="num">${esc(s.items_seen)}</td>
      <td class="num">${esc(s.alerts_raised)}</td>
      <td class="err">${esc(s.last_error_message || "")}</td>
    </tr>`).join("") : `<tr><td colspan="7" class="empty">אין עדיין נתוני מקורות</td></tr>`;

  document.getElementById("alerts").innerHTML = d.alerts.length ? d.alerts.map(a => `
    <tr>
      <td class="num">${esc(clock(a.timestamp))}</td>
      <td><span class="badge b-${esc(a.severity)}">${esc(SEV_HE[a.severity] || a.severity)}</span></td>
      <td>${esc(a.source)}</td>
      <td>${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>`
                  : esc(a.title)}${a.delivered ? "" : ' <span class="err">(לא נשלח)</span>'}</td>
      <td><div class="chips">${a.phrases.map(p => `<span class="chip">${esc(p)}</span>`).join("")}</div></td>
    </tr>`).join("") : `<tr><td colspan="5" class="empty">לא נרשמו התראות</td></tr>`;

  const c = d.config || {};
  document.getElementById("config").textContent =
    `${c.keyword_count ?? "?"} מילות מפתח · ${c.feed_count ?? "?"} פידים · ` +
    `${c.channel_count ?? "?"} ערוצים · מצלמות: ${c.cameras || "לא מוגדר"}`;
  document.getElementById("stamp").textContent = "עודכן " + clock(d.generated_at);
}

async function tick() {
  try {
    const res = await fetch("/api/status" + TOKEN_QUERY, {cache: "no-store"});
    if (!res.ok) throw new Error("HTTP " + res.status);
    render(await res.json());
  } catch (e) {
    document.getElementById("stamp").textContent = "שגיאת עדכון: " + e.message;
  }
}
tick();
setInterval(tick, 10000);
</script>
</body>
</html>
"""
