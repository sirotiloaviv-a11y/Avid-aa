"""A tiny WSGI client so tests exercise the real request pipeline.

Routing, middleware, CSRF and the guards all run — the only thing missing
compared to production is the socket.
"""

from __future__ import annotations

import os
import re
import unittest
from io import BytesIO
from typing import Any
from urllib.parse import urlencode

os.environ.setdefault("DATABASE_PATH", ":memory:")
os.environ.setdefault("PASSWORD_ITERATIONS", "1000")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-suite")
os.environ.setdefault("APP_ENV", "test")

from fitness_platform import wsgi  # noqa: E402
from fitness_platform.config import reset_settings  # noqa: E402
from fitness_platform.db import connection  # noqa: E402
from fitness_platform.services.security import limiter  # noqa: E402

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class Response:
    def __init__(self, status: str, headers: list[tuple[str, str]], body: bytes):
        self.status = int(status.split(" ")[0])
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def location(self) -> str:
        for key, value in self.headers:
            if key.lower() == "location":
                return value
        return ""

    def json(self) -> Any:
        import json

        return json.loads(self.text or "{}")

    def header(self, name: str) -> str:
        for key, value in self.headers:
            if key.lower() == name.lower():
                return value
        return ""

    def csrf(self) -> str:
        match = CSRF_RE.search(self.text)
        return match.group(1) if match else ""


class Client:
    def __init__(self) -> None:
        self.app = wsgi.create_app()
        self.cookies: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        json_body: dict | None = None,
        query: dict | None = None,
        headers: dict | None = None,
    ) -> Response:
        body = b""
        content_type = ""
        if json_body is not None:
            import json

            body = json.dumps(json_body).encode("utf-8")
            content_type = "application/json"
        elif data is not None:
            body = urlencode(data, doseq=True).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"

        path, _, inline_query = path.partition("?")
        query_string = urlencode(query or {}, doseq=True)
        if inline_query:
            query_string = f"{inline_query}&{query_string}" if query_string else inline_query

        environ = {
            "REQUEST_METHOD": method.upper(),
            "PATH_INFO": path,
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(body),
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": content_type,
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_COOKIE": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
        }
        for key, value in (headers or {}).items():
            environ["HTTP_" + key.upper().replace("-", "_")] = value

        captured: dict[str, Any] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = response_headers

        chunks = self.app(environ, start_response)
        response = Response(captured["status"], captured["headers"], b"".join(chunks))
        self._store_cookies(response)
        return response

    def _store_cookies(self, response: Response) -> None:
        for key, value in response.headers:
            if key.lower() != "set-cookie":
                continue
            name, _, rest = value.partition("=")
            cookie_value = rest.split(";")[0]
            if "Max-Age=0" in value:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = cookie_value

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data: dict | None = None, **kwargs) -> Response:
        """POST a form, filling in the CSRF token from the page that owns it."""
        data = dict(data or {})
        if "csrf_token" not in data:
            token = self.csrf_token()
            if token:
                data["csrf_token"] = token
        return self.request("POST", path, data=data, **kwargs)

    def post_json(self, path: str, payload: dict | None = None, **kwargs) -> Response:
        payload = dict(payload or {})
        payload.setdefault("csrf_token", self.csrf_token())
        return self.request("POST", path, json_body=payload, **kwargs)

    def csrf_token(self) -> str:
        from fitness_platform.services.auth import SESSION_COOKIE, session_csrf

        session_id = self.cookies.get(SESSION_COOKIE, "")
        return session_csrf(session_id) if session_id else ""

    # --- convenience flows ------------------------------------------------
    def signup(self, segment: str, email: str, password: str = "secret123", name: str = "משתמש בדיקה") -> Response:
        self.get(f"/start/{segment}")
        return self.post(f"/start/{segment}", {"email": email, "password": password, "name": name})

    def login(self, email: str, password: str = "secret123") -> Response:
        self.get("/login")
        return self.post("/login", {"email": email, "password": password})

    def logout(self) -> Response:
        return self.post("/logout")


class AppTestCase(unittest.TestCase):
    """Base case: a fresh in-memory database per test."""

    def setUp(self) -> None:
        os.environ["DATABASE_PATH"] = ":memory:"
        reset_settings()
        connection.reset_connection()
        limiter.reset()
        self.client = Client()

    def tearDown(self) -> None:
        connection.reset_connection()

    def new_client(self) -> Client:
        return Client()
