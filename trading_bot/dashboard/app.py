"""Dashboard request handling, independent of the socket server.

:class:`DashboardApp` maps a :class:`Request` to a :class:`Response`, so every
route, the auth rules and the CSRF rules are unit-tested without a network.

Security:

* **Basic auth** on everything except ``/healthz``, compared in constant time.
  After too many failures from one address, that address is locked out
  (HTTP 429) for a while, so a password can't be brute-forced.
* **CSRF**: browsers attach Basic-auth credentials automatically, so a
  malicious page could otherwise POST to ``/api/kill``. State-changing
  requests must carry the ``X-Dashboard-Request`` header (which a
  cross-origin page cannot set without a CORS preflight this server never
  approves), a JSON body, and an ``Origin``, if present, matching ``Host``.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, cast
from urllib.parse import parse_qs, unquote, urlsplit

from ..config import DashboardConfig
from ..risk_manager.controls import ALL_ACCOUNTS, ControlAction, ControlResult, OperatorControls
from ..risk_manager.events import RiskEvent
from ..risk_manager.news_guard import NewsGuard
from ..risk_manager.risk_engine import RiskManager
from ..utils.logger import get_logger
from ..utils.state_store import StateStore, StateStoreError
from ..utils.time_utils import utc_now
from .state import build_snapshot, news_view, trade_view

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
}
CSRF_HEADER = "x-dashboard-request"
MAX_BODY = 4096
SNAPSHOT_TRADES = 100
SNAPSHOT_EVENTS = 50


@dataclass(frozen=True)
class Request:
    method: str
    target: str
    # Header names in lower case.
    headers: Mapping[str, str] = field(default_factory=lambda: dict[str, str]())
    body: bytes = b""
    client: str = "unknown"

    @property
    def path(self) -> str:
        return unquote(urlsplit(self.target).path)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.target).query)


@dataclass
class Response:
    status: int
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    @classmethod
    def json(cls, payload: Any, status: int = 200) -> Response:
        return cls(status, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    @classmethod
    def error(cls, status: int, message: str) -> Response:
        return cls.json({"error": message}, status)


class AuthThrottle:
    """Locks out an address after ``max_failures`` bad logins within ``window``."""

    def __init__(self, max_failures: int = 10, window: float = 300.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window = window
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, client: str) -> deque[float]:
        entries = self._failures.setdefault(client, deque())
        cutoff = self._clock() - self.window
        while entries and entries[0] < cutoff:
            entries.popleft()
        return entries

    def locked(self, client: str) -> bool:
        with self._lock:
            return len(self._recent(client)) >= self.max_failures

    def fail(self, client: str) -> None:
        with self._lock:
            self._recent(client).append(self._clock())

    def succeed(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


class DashboardApp:
    def __init__(
        self,
        *,
        manager: RiskManager,
        controls: OperatorControls,
        store: StateStore,
        news_guard: NewsGuard | None,
        config: DashboardConfig,
        environment: str,
        stale_after: timedelta,
        clock: Callable[[], datetime] = utc_now,
        static_dir: Path = STATIC_DIR,
        throttle: AuthThrottle | None = None,
    ) -> None:
        if not config.enabled:
            raise ValueError("dashboard needs DASHBOARD_PASSWORD")
        self.manager = manager
        self.controls = controls
        self.store = store
        self.news_guard = news_guard
        self.config = config
        self.environment = environment
        self.stale_after = stale_after
        self._clock = clock
        self.static_dir = static_dir
        self.throttle = throttle or AuthThrottle()
        self._expected = f"{config.username}:{config.password.get()}".encode("utf-8")
        self._changed = threading.Condition()
        self._version = 0
        manager.subscribe(self.on_risk_event)

    # ------------------------------------------------------- change signal
    def on_risk_event(self, _event: RiskEvent) -> None:
        self.notify_change()

    def notify_change(self) -> None:
        with self._changed:
            self._version += 1
            self._changed.notify_all()

    def wait_for_change(self, seen: int, timeout: float) -> int:
        """Block until the version moves past ``seen`` or ``timeout`` passes."""
        with self._changed:
            self._changed.wait_for(lambda: self._version != seen, timeout)
            return self._version

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        try:
            trades = self.store.recent_trades(SNAPSHOT_TRADES)
            events = self.store.recent_events_all(SNAPSHOT_EVENTS)
        except StateStoreError as exc:
            log.error("Dashboard could not read the journal: %s", exc)
            trades, events = [], []
        guard = self.news_guard
        if guard is not None and guard.enabled:
            news = news_view(guard.upcoming(now, within=timedelta(days=7)),
                             guard.check(now, refresh=False), enabled=True)
        else:
            news = news_view([], None, enabled=False)
        return build_snapshot(
            self.manager.statuses(now=now), trades, events,
            kill_switch=self.controls.kill_switch_active, news=news,
            environment=self.environment, now=now, stale_after=self.stale_after,
            high_risk_pct=self.config.high_risk_pct,
        )

    # ---------------------------------------------------------------- auth
    def authorize(self, request: Request) -> Response | None:
        """None if authorised, else the response to send."""
        if self.throttle.locked(request.client):
            return Response.error(429, "too many failed logins; try again later")
        header = request.headers.get("authorization", "")
        scheme, _, encoded = header.partition(" ")
        supplied = b""
        if scheme.lower() == "basic":
            try:
                supplied = base64.b64decode(encoded.strip(), validate=True)
            except (binascii.Error, ValueError):
                supplied = b""
        if supplied and hmac.compare_digest(supplied, self._expected):
            self.throttle.succeed(request.client)
            return None
        if header:
            self.throttle.fail(request.client)
            log.warning("Dashboard login failed from %s", request.client)
        response = Response.error(401, "authentication required")
        response.headers["WWW-Authenticate"] = 'Basic realm="Trading Bot", charset="UTF-8"'
        return response

    def _csrf_problem(self, request: Request) -> str | None:
        if request.headers.get(CSRF_HEADER) != "1":
            return "missing X-Dashboard-Request header"
        if not request.headers.get("content-type", "").startswith("application/json"):
            return "content type must be application/json"
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            return "cross-origin request refused"
        return None

    # -------------------------------------------------------------- routing
    def handle(self, request: Request) -> Response:
        try:
            return self._handle(request)
        except Exception:
            log.exception("Dashboard error on %s %s", request.method, request.path)
            return Response.error(500, "internal error")

    def _handle(self, request: Request) -> Response:
        path = request.path
        if path == "/healthz" and request.method in ("GET", "HEAD"):
            return Response.json({"ok": True})
        denied = self.authorize(request)
        if denied is not None:
            return denied

        if request.method in ("GET", "HEAD"):
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path.removeprefix("/static/"))
            if path == "/api/state":
                return Response.json(self.snapshot())
            if path == "/api/trades":
                return self._trades(request)
            return Response.error(404, "not found")

        if request.method != "POST":
            return Response.error(405, "method not allowed")
        problem = self._csrf_problem(request)
        if problem:
            return Response.error(403, problem)
        if len(request.body) > MAX_BODY:
            return Response.error(413, "request body too large")
        try:
            raw: Any = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response.error(400, "body must be JSON")
        if not isinstance(raw, dict):
            return Response.error(400, "body must be a JSON object")
        body = cast("dict[str, Any]", raw)
        reason = str(body.get("reason") or "").strip()[:200]
        operator = f"dashboard:{self.config.username}@{request.client}"

        if path == "/api/kill":
            return self._control(ControlAction.EMERGENCY_HALT, ALL_ACCOUNTS,
                                 reason or "kill switch from dashboard", operator)
        if path == "/api/resume":
            return self._control(ControlAction.RESUME_ALL, ALL_ACCOUNTS, "", operator)
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "accounts"] and parts[3] in ("pause", "unpause"):
            action = ControlAction.PAUSE if parts[3] == "pause" else ControlAction.UNPAUSE
            return self._control(action, parts[2], reason or "paused from dashboard", operator)
        return Response.error(404, "not found")

    def _control(self, action: ControlAction, account_id: str, argument: str, operator: str) -> Response:
        result: ControlResult = self.controls.apply(action, account_id, argument, operator)
        self.notify_change()
        status = 200 if result.ok else (404 if result.message.startswith("unknown account") else 500)
        return Response.json({"ok": result.ok, "message": result.message}, status)

    def _trades(self, request: Request) -> Response:
        query = request.query
        try:
            limit = max(1, min(1000, int(query.get("limit", ["200"])[0])))
        except ValueError:
            return Response.error(400, "limit must be an integer")
        account = query.get("account", [None])[0] or None
        trades = self.store.recent_trades(limit, account_id=account)
        return Response.json({"trades": [trade_view(t) for t in trades]})

    def _static(self, name: str) -> Response:
        content_type = STATIC_FILES.get(name)
        if content_type is None:  # allow-list: no path traversal possible
            return Response.error(404, "not found")
        try:
            body = (self.static_dir / name).read_bytes()
        except OSError:
            return Response.error(404, "not found")
        return Response(200, body, content_type)
