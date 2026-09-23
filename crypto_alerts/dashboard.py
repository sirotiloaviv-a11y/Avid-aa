"""Live web dashboard, served from inside the alert process.

    GET  /            the dashboard (HTML; polls /api/state every 2 s)
    GET  /api/state   symbols, alert log, risk metrics, channel stats (JSON)
    POST /api/risk    {"account_equity": 250000, "risk_per_trade_pct": 0.75}
    GET  /healthz     "ok" — for a container or uptime check

Why in-process and dependency-free rather than Streamlit: the dashboard reads
the engine's live state directly, and a risk change made here is applied to
the very next alert, with no IPC, database or second process. It is plain
``asyncio.start_server`` with just enough HTTP/1.1 for four routes, so it adds
no dependency and no web framework to a trading tool.

SECURITY
--------
This page can change position sizing, so it is treated as a control surface:

* Binds to 127.0.0.1 by default. Config refuses a non-loopback host without
  ``DASHBOARD_TOKEN``. Put TLS in front (reverse proxy / SSH tunnel) if you
  expose it at all.
* With a token, requests need ``Authorization: Bearer <token>`` or the
  session cookie set by opening ``/?token=<token>`` once.
* Without a token, the Host header must be a loopback name, which blocks DNS
  rebinding (a malicious site resolving its own name to 127.0.0.1).
* POST /api/risk needs a per-process CSRF token in a custom header — a
  cross-site form or fetch cannot set it — and a same-origin Origin header.
* Strict CSP with per-response nonces, no framing, and all data is rendered
  with ``textContent``: exchange error strings never become markup.
* Every change is logged, shown on the page, and announced on Telegram.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qs, urlsplit

from .config import LOOPBACK_HOSTS, DashboardSettings
from .risk_manager import RiskError

if TYPE_CHECKING:
    from .main import AlertEngine

log = logging.getLogger(__name__)

MAX_HEADER_BYTES = 16 * 1024
MAX_BODY_BYTES = 4 * 1024
READ_TIMEOUT_SECONDS = 10
COOKIE_NAME = "ca_session"

_REASONS = {200: "OK", 204: "No Content", 302: "Found", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large",
            422: "Unprocessable Entity"}


class Request:
    def __init__(self, method: str, target: str, headers: dict[str, str], body: bytes) -> None:
        self.method = method
        parts = urlsplit(target)
        self.path = parts.path
        self.query = parse_qs(parts.query)
        self.headers = headers
        self.body = body

    def cookie(self, name: str) -> Optional[str]:
        for part in self.headers.get("cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None


class Response:
    def __init__(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8",
                 headers: Optional[dict[str, str]] = None) -> None:
        self.status = status
        self.body = body
        self.headers = {"Content-Type": content_type, **(headers or {})}

    @classmethod
    def json(cls, status: int, data: Any) -> "Response":
        return cls(status, json.dumps(data, allow_nan=False, default=str).encode(), "application/json")


class DashboardServer:
    def __init__(self, engine: "AlertEngine", settings: DashboardSettings) -> None:
        self.engine = engine
        self.settings = settings
        self._csrf = secrets.token_urlsafe(32)
        self._server: Optional[asyncio.base_events.Server] = None

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> tuple[str, int]:
        self._server = await asyncio.start_server(self._handle, self.settings.host, self.settings.port)
        host, port = self._server.sockets[0].getsockname()[:2]
        log.info("Dashboard on http://%s:%d/ (token %s)", host, port,
                 "required" if self.settings.token else "not set — loopback only")
        return host, port

    async def run(self, stop: asyncio.Event) -> None:
        try:
            await self.start()
        except OSError as exc:
            log.error("Dashboard could not bind %s:%d — %s", self.settings.host, self.settings.port, exc)
            return
        try:
            await stop.wait()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ------------------------------------------------------------------ HTTP

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(self._read(reader), READ_TIMEOUT_SECONDS)
            response = self.route(request) if isinstance(request, Request) else request
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        except Exception:
            log.exception("Dashboard request failed")
            response = Response(500, b"internal error")
        try:
            writer.write(self._serialise(response))
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def _read(self, reader: asyncio.StreamReader) -> Request | Response:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError:
            return Response(413, b"headers too large")
        if len(head) > MAX_HEADER_BYTES:
            return Response(413, b"headers too large")
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _ = lines[0].split(" ", 2)
        except ValueError:
            return Response(400, b"bad request line")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()
        try:
            length = int(headers.get("content-length", "0") or 0)
        except ValueError:
            return Response(400, b"bad content-length")
        if length < 0 or length > MAX_BODY_BYTES:
            return Response(413, b"body too large")
        body = await reader.readexactly(length) if length else b""
        return Request(method.upper(), target, headers, body)

    @staticmethod
    def _serialise(response: Response) -> bytes:
        headers = {
            **response.headers,
            "Content-Length": str(len(response.body)),
            "Connection": "close",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        }
        head = f"HTTP/1.1 {response.status} {_REASONS.get(response.status, 'Error')}\r\n"
        head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        return (head + "\r\n").encode("latin-1") + response.body

    # --------------------------------------------------------------- routing

    def route(self, request: Request) -> Response:
        if request.path == "/healthz":
            return Response(200, b"ok")
        if not self._host_allowed(request):
            return Response(403, b"host not allowed")

        query_token = (request.query.get("token") or [""])[0]
        if not self._authorised(request, query_token):
            return Response(401, b"unauthorised: open /?token=<DASHBOARD_TOKEN>")

        if request.path == "/" and request.method == "GET":
            if query_token and self.settings.token:
                # Swap the token in the URL for a cookie, and drop it from the address bar.
                cookie = f"{COOKIE_NAME}={query_token}; HttpOnly; SameSite=Strict; Path=/"
                return Response(302, headers={"Location": "/", "Set-Cookie": cookie})
            nonce = secrets.token_urlsafe(16)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                   "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            return Response(200, render_page(self._csrf, nonce).encode(), "text/html; charset=utf-8",
                            {"Content-Security-Policy": csp})
        if request.path == "/api/state":
            if request.method != "GET":
                return Response(405, b"method not allowed")
            return Response.json(200, self.snapshot())
        if request.path == "/api/risk":
            if request.method != "POST":
                return Response(405, b"method not allowed")
            return self._update_risk(request)
        return Response(404, b"not found")

    def _host_allowed(self, request: Request) -> bool:
        if self.settings.token:
            return True  # the token, not the Host header, is the boundary
        host = request.headers.get("host", "")
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host[1:].split("]", 1)[0]
        return hostname in LOOPBACK_HOSTS

    def _authorised(self, request: Request, query_token: str) -> bool:
        expected = self.settings.token
        if not expected:
            return True
        auth = request.headers.get("authorization", "")
        candidates = [
            auth[7:] if auth.lower().startswith("bearer ") else "",
            request.cookie(COOKIE_NAME) or "",
            query_token if request.path == "/" else "",
        ]
        return any(c and hmac.compare_digest(c.encode(), expected.encode()) for c in candidates)

    def _update_risk(self, request: Request) -> Response:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), self._csrf.encode()):
            return Response.json(403, {"error": "missing or invalid CSRF token — reload the page"})
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            return Response.json(403, {"error": "cross-origin request refused"})
        if "application/json" not in request.headers.get("content-type", ""):
            return Response.json(400, {"error": "expected application/json"})
        try:
            data = json.loads(request.body or b"{}")
            if not isinstance(data, dict):
                raise ValueError
            equity = _number(data.get("account_equity"))
            risk_pct = _number(data.get("risk_per_trade_pct"))
        except ValueError:
            return Response.json(400, {"error": "account_equity and risk_per_trade_pct must be numbers"})
        if equity is None and risk_pct is None:
            return Response.json(400, {"error": "nothing to change"})
        try:
            applied = self.engine.update_risk(equity, risk_pct, source="dashboard")
        except RiskError as exc:
            return Response.json(422, {"error": str(exc)})
        return Response.json(200, {"ok": True, "risk": applied})

    def snapshot(self) -> dict[str, Any]:
        engine = self.engine
        return engine.state.snapshot(
            engine.settings,
            engine.risk.settings,
            {
                "delivery": engine.dispatcher.snapshot(),
                "server_time_ms": int(time.time() * 1000),
            },
        )


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError
    return number


def render_page(csrf: str, nonce: str) -> str:
    return _PAGE.replace("{{CSRF}}", csrf).replace("{{NONCE}}", nonce)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{{CSRF}}">
<title>Crypto Alerts</title>
<style nonce="{{NONCE}}">
:root { --bg:#f6f7f9; --panel:#fff; --text:#1b1f24; --muted:#667085; --line:#e4e7ec;
        --long:#12805c; --short:#c0392b; --warn:#b54708; --accent:#2f5bd3; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f1115; --panel:#171a21; --text:#e6e8eb; --muted:#8b93a1; --line:#262b35;
          --long:#3ccf91; --short:#ff6b5e; --warn:#f5a524; --accent:#7aa2ff; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
header { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; padding:14px 16px;
         border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; z-index:1; }
header h1 { font-size:16px; margin:0; }
.muted { color:var(--muted); }
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--muted); margin-right:6px; }
.dot.ok { background:var(--long); } .dot.bad { background:var(--short); }
main { max-width:1200px; margin:0 auto; padding:16px; display:grid; gap:16px; }
section { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; min-width:0; }
section h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 10px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.kpi { border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.kpi .v { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; }
.kpi .l { color:var(--muted); font-size:12px; }
.table { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
th { color:var(--muted); font-weight:500; font-size:12px; }
td.wrap { white-space:normal; min-width:220px; }
.long { color:var(--long); font-weight:600; } .short { color:var(--short); font-weight:600; }
.warn { color:var(--warn); } .bad { color:var(--short); }
.tag { display:inline-block; padding:1px 7px; border-radius:99px; font-size:12px; border:1px solid var(--line); }
form { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
label { display:grid; gap:4px; font-size:12px; color:var(--muted); }
input { font:inherit; padding:7px 9px; border:1px solid var(--line); border-radius:6px;
        background:var(--bg); color:var(--text); width:170px; }
button { font:inherit; padding:7px 14px; border-radius:6px; border:0; background:var(--accent); color:#fff; cursor:pointer; }
#risk-msg { font-size:13px; }
.empty { color:var(--muted); padding:8px 0; }
</style>
</head>
<body>
<header>
  <h1>📈 Crypto Alerts</h1>
  <span id="conn"><span class="dot"></span>connecting…</span>
  <span class="muted" id="meta"></span>
</header>
<main>
  <section>
    <h2>Risk metrics</h2>
    <div class="kpis" id="kpis"></div>
  </section>
  <section>
    <h2>Adjust risk (applies to the next alert)</h2>
    <form id="risk-form">
      <label>Account equity (USD)<input id="equity" type="number" min="1" step="any" required></label>
      <label>Risk per trade (%)<input id="riskpct" type="number" min="0.01" max="5" step="0.01" required></label>
      <button type="submit">Apply</button>
      <span id="risk-msg" class="muted"></span>
    </form>
  </section>
  <section>
    <h2>Symbols</h2>
    <div class="table"><table>
      <thead><tr><th>Symbol</th><th>Feed</th><th>Price</th><th>Updated</th><th>RSI</th><th>Vol ×</th>
      <th>ATR</th><th>Alerts</th><th>Reconnects</th><th>Last error</th></tr></thead>
      <tbody id="symbols"></tbody>
    </table></div>
  </section>
  <section>
    <h2>Alert log</h2>
    <div class="table"><table>
      <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Status</th><th>Entry</th><th>SL</th><th>TP</th>
      <th>Size</th><th>Risk</th><th>Slippage</th><th>Details</th></tr></thead>
      <tbody id="alerts"></tbody>
    </table></div>
  </section>
  <section>
    <h2>Delivery</h2>
    <div class="table"><table>
      <thead><tr><th>Channel</th><th>Sent</th><th>Failed</th><th>Last error</th></tr></thead>
      <tbody id="channels"></tbody>
    </table></div>
  </section>
</main>
<script nonce="{{NONCE}}">
"use strict";
const CSRF = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const usd = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
const num = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
const price = (v) => v == null ? "—" : num(v, v >= 1000 ? 2 : v >= 1 ? 4 : 8);
const sig4 = (v) => v == null ? "—" : v >= 1 ? price(v) : Number(v.toPrecision(4)).toString();
const ago = (ms, now) => {
  if (ms == null) return "—";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + "m ago" : Math.round(s / 3600) + "h ago";
};
const time = (ms) => new Date(ms).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});

function cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text == null ? "—" : String(text);   // never innerHTML: data is untrusted
  if (cls) td.className = cls;
  return td;
}
function fill(tbody, rows, cols, emptyText) {
  tbody.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = cell(emptyText, "empty"); td.colSpan = cols;
    tr.append(td); tbody.append(tr); return;
  }
  for (const cells of rows) { const tr = document.createElement("tr"); tr.append(...cells); tbody.append(tr); }
}
function kpi(label, value, cls) {
  const d = document.createElement("div"); d.className = "kpi";
  const v = document.createElement("div"); v.className = "v" + (cls ? " " + cls : ""); v.textContent = value;
  const l = document.createElement("div"); l.className = "l"; l.textContent = label;
  d.append(v, l); return d;
}

let formTouched = false;
["equity", "riskpct"].forEach((id) => $(id).addEventListener("input", () => { formTouched = true; }));

function render(s) {
  const r = s.risk, d = s.last_24h, now = s.now_ms;
  $("meta").textContent = `${s.exchange} · ${s.timeframe} · up ${ago(s.started_ms, now).replace(" ago", "")}`;
  $("kpis").replaceChildren(
    kpi("Account equity", usd(r.account_equity)),
    kpi("Risk per trade", num(r.risk_per_trade_pct, 3) + "%"),
    kpi("$ at risk per trade", usd(r.risk_budget)),
    kpi("Target R:R", "1 : " + num(r.risk_reward_ratio)),
    kpi("Max leverage", num(r.max_leverage) + "x"),
    kpi("Slippage limit", r.liquidity_check ? num(r.max_slippage_pct, 3) + "% · " + r.liquidity_action : "off"),
    kpi("Alerts (24h)", String(d.alerts_sent)),
    kpi("Urgent (24h)", String(d.urgent), d.urgent ? "warn" : ""),
    kpi("Filtered by liquidity (24h)", String(d.filtered)),
    kpi("Risk if all stopped (24h)", usd(d.risk_if_all_stopped), d.risk_if_all_stopped > r.account_equity * 0.05 ? "bad" : ""),
  );
  if (!formTouched) { $("equity").value = r.account_equity; $("riskpct").value = r.risk_per_trade_pct; }

  fill($("symbols"), s.symbols.map((x) => {
    const stale = x.updated_ms != null && now - x.updated_ms > 120000;
    const feedCls = x.feed_state === "live" && !stale ? "long" : x.feed_state === "stopped" ? "bad" : "warn";
    return [cell(x.symbol), cell(stale ? "stale" : x.feed_state, feedCls), cell(price(x.price)),
      cell(ago(x.updated_ms, now)), cell(num(x.rsi, 1)), cell(num(x.volume_ratio, 2)), cell(sig4(x.atr)),
      cell(x.signals), cell(x.reconnects), cell(x.last_error, "wrap muted")];
  }), 10, "No symbols");

  fill($("alerts"), s.alerts.map((a) => {
    const side = a.direction === "LONG" ? "long" : "short";
    const statusCls = a.status === "sent" ? (a.urgent ? "warn" : "") : "muted";
    const status = a.status === "sent" && a.urgent ? "sent · URGENT" : a.status;
    const details = [a.summary, a.conviction.length ? "🔥 " + a.conviction.join(", ") : "",
      a.liquidity && a.liquidity !== "ok" && a.liquidity !== "unchecked" ? "liquidity: " + a.liquidity : "", a.note]
      .filter(Boolean).join(" · ");
    return [cell(time(a.time_ms)), cell(a.symbol), cell(a.direction, side), cell(status, statusCls),
      cell(price(a.entry)), cell(price(a.stop_loss)), cell(price(a.take_profit)), cell(usd(a.notional)),
      cell(usd(a.risk_amount)),
      cell(a.slippage_pct != null ? num(a.slippage_pct, 3) + "%" : a.liquidity === "warned" || a.liquidity === "filtered" ? "book too thin" : "—",
        a.liquidity === "warned" || a.liquidity === "filtered" ? "bad" : ""),
      cell(details, "wrap")];
  }), 11, "No alerts yet — signals appear here as candles close");

  const ch = Object.entries(s.delivery.channels);
  fill($("channels"), ch.map(([name, c]) => [cell(name), cell(c.sent), cell(c.failed, c.failed ? "bad" : ""),
    cell(c.last_error, "wrap muted")]), 4, "No channels");
}

async function refresh() {
  try {
    const res = await fetch("/api/state", {credentials: "same-origin", cache: "no-store"});
    if (!res.ok) throw new Error("HTTP " + res.status);
    render(await res.json());
    $("conn").replaceChildren(Object.assign(document.createElement("span"), {className: "dot ok"}), "live");
  } catch (err) {
    $("conn").replaceChildren(Object.assign(document.createElement("span"), {className: "dot bad"}),
      "disconnected (" + err.message + ")");
  }
}

$("risk-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = {account_equity: $("equity").value, risk_per_trade_pct: $("riskpct").value};
  const msg = $("risk-msg");
  msg.className = "muted"; msg.textContent = "Applying…";
  try {
    const res = await fetch("/api/risk", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": CSRF}, body: JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
    formTouched = false;
    msg.className = "long";
    msg.textContent = `Applied: ${usd(data.risk.account_equity)} at ${num(data.risk.risk_per_trade_pct, 3)}%`;
    refresh();
  } catch (err) {
    msg.className = "bad"; msg.textContent = err.message;
  }
});

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
