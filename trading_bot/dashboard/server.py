"""HTTP server for the dashboard (standard library, threaded).

Adapts :class:`~trading_bot.dashboard.app.DashboardApp` to
``http.server`` and adds the one streaming route, ``/api/stream``
(Server-Sent Events). The stream pushes a fresh snapshot whenever a risk
event fires, and otherwise re-checks every couple of seconds, which also
catches changes made by other processes (the CLI, the KILL file).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from ..utils.logger import get_logger
from .app import DashboardApp, Request, Response

log = get_logger(__name__)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
MAX_STREAMS = 16
STREAM_RECHECK_SECONDS = 2.0
STREAM_PING_SECONDS = 15.0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TradingBotDashboard"
    sys_version = ""

    @property
    def dashboard(self) -> DashboardHTTPServer:
        return cast(DashboardHTTPServer, self.server)

    def _request(self) -> Request:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, 64 * 1024)) if length > 0 else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        return Request(self.command, self.path, headers, body, self.client_address[0])

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in {**SECURITY_HEADERS, **response.headers}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def do_GET(self) -> None:  # noqa: N802
        request = self._request()
        if request.path == "/api/stream":
            self._stream(request)
        else:
            self._send(self.dashboard.app.handle(request))

    do_HEAD = do_GET  # noqa: N815

    def do_POST(self) -> None:  # noqa: N802
        self._send(self.dashboard.app.handle(self._request()))

    def _stream(self, request: Request) -> None:
        app = self.dashboard.app
        denied = app.authorize(request)
        if denied is not None:
            self._send(denied)
            return
        if not self.dashboard.streams.acquire(blocking=False):
            self._send(Response.error(503, "too many open streams"))
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Accel-Buffering", "no")  # nginx: don't buffer
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            self.close_connection = True
            self._pump(app)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # browser went away
        finally:
            self.dashboard.streams.release()

    def _pump(self, app: DashboardApp) -> None:
        last_key: str | None = None
        last_write = time.monotonic()
        version = -1
        while not self.dashboard.stopping.is_set():
            snapshot: dict[str, Any] = app.snapshot()
            key = json.dumps({k: v for k, v in snapshot.items() if k != "server_time"}, sort_keys=True)
            now = time.monotonic()
            if key != last_key:
                data = json.dumps(snapshot, separators=(",", ":"))
                self.wfile.write(f"event: state\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
                last_key, last_write = key, now
            elif now - last_write > STREAM_PING_SECONDS:
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                last_write = now
            version = app.wait_for_change(version, STREAM_RECHECK_SECONDS)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug("%s %s", self.client_address[0], format % args)


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: DashboardApp) -> None:
        super().__init__(address, _Handler)
        self.app = app
        self.stopping = threading.Event()
        self.streams = threading.BoundedSemaphore(MAX_STREAMS)


class DashboardServer:
    """Runs the dashboard on a background thread next to the trading loop."""

    def __init__(self, app: DashboardApp, host: str, port: int) -> None:
        self.app = app
        self.httpd = DashboardHTTPServer((host, port), app)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="dashboard", daemon=True)
        self._thread.start()
        host = self.httpd.server_address[0]
        log.info("Dashboard listening on http://%s:%d", host, self.port)

    def stop(self) -> None:
        self.httpd.stopping.set()
        self.app.notify_change()  # wake open streams so they exit
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None
