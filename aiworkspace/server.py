"""HTTP server: JSON API, a Server-Sent Events reply stream, and the static UI.

Security model (phase 1, single local user, no authentication):
  * binds to loopback only (enforced in config),
  * rejects requests whose Host header is not this loopback address, which
    blocks DNS-rebinding attacks from web pages,
  * requires a custom header plus a matching or absent Origin on every
    state-changing request, so other sites cannot forge them (CSRF),
  * sends a strict Content-Security-Policy; the UI builds the DOM with
    textContent and never evaluates model output as HTML or code,
  * logs method, route and status only, never bodies or titles.
"""

from __future__ import annotations

import json
import logging
import re
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .chat import DEFAULT_TITLE, Busy, ChatService
from .config import Settings
from .providers import build_provider
from .providers.base import TextProvider
from .ratelimit import RateLimiter
from .store import Store
from .validation import (
    ValidationError,
    parse_json_object,
    validate_id,
    validate_message,
    validate_title,
)

log = logging.getLogger("aiworkspace")

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/markdown.js": ("markdown.js", "text/javascript; charset=utf-8"),
    "/static/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/icon.svg": ("icon.svg", "image/svg+xml"),
}
CSRF_HEADER = "X-AIWS-Request"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
CONV_RE = re.compile(r"^/api/conversations/([^/]+)$")
CONV_ACTION_RE = re.compile(r"^/api/conversations/([^/]+)/(messages|cancel)$")


class App:
    """Everything a request handler needs, built once at startup."""

    def __init__(self, settings: Settings, provider: TextProvider | None = None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.provider = provider or build_provider(settings)
        self.chat = ChatService(
            self.store,
            self.provider,
            max_output_tokens=settings.max_output_tokens,
            max_context_chars=settings.max_context_chars,
            request_timeout_s=settings.request_timeout_s,
        )
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self.max_body = settings.max_message_chars * 4 + 4096

    def allowed_hosts(self, port: int) -> set[str]:
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def status(self) -> dict[str, object]:
        return {
            "version": __version__,
            "provider": self.provider.name,
            "model": self.provider.model,
            "simulated": self.provider.simulated,
            "limits": {
                "max_message_chars": self.settings.max_message_chars,
                "max_output_tokens": self.settings.max_output_tokens,
                "rate_limit_per_minute": self.settings.rate_limit_per_minute,
                "request_timeout_s": self.settings.request_timeout_s,
            },
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "aiworkspace"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60  # socket timeout for reading requests and writing responses
    app: App  # set on the subclass created by make_server

    # logging -------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # replaced by log_request below

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        route = getattr(self, "path", "").split("?", 1)[0]
        route = re.sub(r"[0-9a-f]{32}", ":id", route)[:200]
        log.info("%s %s %s", self.command or "-", route, code)

    # response helpers ----------------------------------------------------

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, **extra: object) -> None:
        # The request body may be unread; never reuse this connection.
        self.close_connection = True
        self._json(status, {"error": message, **extra})

    def _read_json(self) -> dict[str, object]:
        ctype = self.headers.get("Content-Type", "")
        if ctype.split(";")[0].strip().lower() != "application/json":
            raise ValidationError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("Invalid Content-Length") from exc
        if length <= 0:
            raise ValidationError("Request body is required")
        if length > self.app.max_body:
            self.close_connection = True
            raise ValidationError("Request body is too large")
        return parse_json_object(self.rfile.read(length))

    # request gatekeeping -------------------------------------------------

    def _port(self) -> int:
        return int(self.server.server_address[1])  # type: ignore[index]

    def _host_ok(self) -> bool:
        port = self._port()
        return self.headers.get("Host", "") in self.app.allowed_hosts(port)

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        port = self._port()
        return origin in {f"http://{h}" for h in self.app.allowed_hosts(port)}

    def _guard(self, mutating: bool) -> bool:
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header")
            return False
        if mutating and (self.headers.get(CSRF_HEADER) != "1" or not self._origin_ok()):
            self._error(HTTPStatus.FORBIDDEN, "Cross-site request refused")
            return False
        return True

    # routing -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard(mutating=False):
            return
        path = self.path.split("?", 1)[0]
        if path in STATIC_FILES:
            return self._static(*STATIC_FILES[path])
        if path == "/api/status":
            return self._json(200, self.app.status())
        if path == "/api/conversations":
            convs = [c.to_dict() for c in self.app.store.list_conversations()]
            return self._json(200, {"conversations": convs})
        m = CONV_RE.match(path)
        if m:
            return self._with_id(m.group(1), self._get_conversation)
        self._error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard(mutating=True):
            return
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/conversations":
                return self._create_conversation()
            m = CONV_ACTION_RE.match(path)
            if m:
                cid = validate_id(m.group(1))
                if m.group(2) == "cancel":
                    return self._json(200, {"cancelled": self.app.chat.cancel(cid)})
                return self._send_message(cid)
        except ValidationError as exc:
            return self._error(400, str(exc))
        self._error(404, "Not found")

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._guard(mutating=True):
            return
        m = CONV_RE.match(self.path.split("?", 1)[0])
        if not m:
            return self._error(404, "Not found")
        self._with_id(m.group(1), self._rename_conversation)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._guard(mutating=True):
            return
        m = CONV_RE.match(self.path.split("?", 1)[0])
        if not m:
            return self._error(404, "Not found")
        self._with_id(m.group(1), self._delete_conversation)

    def _with_id(self, raw: str, fn: Any) -> None:
        try:
            fn(validate_id(raw))
        except ValidationError as exc:
            self._error(400, str(exc))

    # handlers ------------------------------------------------------------

    def _static(self, name: str, ctype: str) -> None:
        body = (STATIC_DIR / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _get_conversation(self, cid: str) -> None:
        conv = self.app.store.get_conversation(cid)
        if conv is None:
            return self._error(404, "Conversation not found")
        messages = [m.to_dict() for m in self.app.store.list_messages(cid)]
        self._json(
            200,
            {
                "conversation": conv.to_dict(),
                "messages": messages,
                "busy": self.app.chat.is_busy(cid),
            },
        )

    def _create_conversation(self) -> None:
        title = DEFAULT_TITLE
        if int(self.headers.get("Content-Length", "0") or 0) > 0:
            data = self._read_json()
            if "title" in data:
                title = validate_title(data["title"], self.app.settings.max_title_chars)
        conv = self.app.store.create_conversation(title)
        self._json(201, {"conversation": conv.to_dict()})

    def _rename_conversation(self, cid: str) -> None:
        data = self._read_json()
        title = validate_title(data.get("title"), self.app.settings.max_title_chars)
        conv = self.app.store.rename_conversation(cid, title)
        if conv is None:
            return self._error(404, "Conversation not found")
        self._json(200, {"conversation": conv.to_dict()})

    def _delete_conversation(self, cid: str) -> None:
        self.app.chat.cancel(cid)
        if not self.app.store.delete_conversation(cid):
            return self._error(404, "Conversation not found")
        self._json(200, {"deleted": True})

    def _send_message(self, cid: str) -> None:
        data = self._read_json()
        text = validate_message(
            data.get("content"), self.app.settings.max_message_chars
        )
        if self.app.store.get_conversation(cid) is None:
            return self._error(404, "Conversation not found")
        if self.app.chat.is_busy(cid):
            return self._error(
                409, "A reply is already being generated for this conversation"
            )
        wait = self.app.limiter.try_acquire()
        if wait:
            return self._error(
                429,
                "Too many messages. Please wait a moment.",
                retry_after_s=round(wait, 1),
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        self.close_connection = True

        def emit(event: str, payload: dict[str, object]) -> None:
            data_line = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"event: {event}\ndata: {data_line}\n\n".encode("utf-8"))
            self.wfile.flush()

        def ping() -> None:
            self.wfile.write(b": ping\n\n")
            self.wfile.flush()

        try:
            self.app.chat.reply(cid, text, emit, ping)
        except Busy:
            emit("error", {"message": "A reply is already being generated."})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(app: App, port: int | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    host = app.settings.host
    server_cls: type[ThreadingHTTPServer] = _Server
    if ":" in host:
        server_cls = type("_Server6", (_Server,), {"address_family": socket.AF_INET6})
    bind_port = app.settings.port if port is None else port
    return server_cls((host, bind_port), handler)
