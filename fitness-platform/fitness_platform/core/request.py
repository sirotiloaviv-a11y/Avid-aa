"""A thin, typed wrapper over the WSGI environ."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Mapping
from urllib.parse import parse_qs

MAX_BODY_BYTES = 1024 * 1024  # 1 MiB is plenty for form posts and chat turns.


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    cookies: dict[str, str]
    body: bytes
    remote_addr: str
    environ: Mapping[str, Any] = field(repr=False, default_factory=dict)

    # Populated by middleware / routing.
    params: dict[str, str] = field(default_factory=dict)
    user: Any = None
    session: Any = None
    csrf_token: str = ""

    @classmethod
    def from_environ(cls, environ: Mapping[str, Any]) -> "Request":
        headers: dict[str, str] = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                headers[key[5:].replace("_", "-").lower()] = value
        for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            if environ.get(key):
                headers[key.replace("_", "-").lower()] = environ[key]

        try:
            length = min(int(environ.get("CONTENT_LENGTH") or 0), MAX_BODY_BYTES)
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(length) if length else b""

        cookies: dict[str, str] = {}
        raw_cookie = headers.get("cookie", "")
        if raw_cookie:
            jar = SimpleCookie()
            try:
                jar.load(raw_cookie)
            except Exception:  # malformed cookie header: ignore rather than 500
                jar = SimpleCookie()
            cookies = {key: morsel.value for key, morsel in jar.items()}

        forwarded = headers.get("x-forwarded-for", "")
        remote = forwarded.split(",")[0].strip() if forwarded else environ.get("REMOTE_ADDR", "")

        return cls(
            method=environ.get("REQUEST_METHOD", "GET").upper(),
            path=environ.get("PATH_INFO", "/") or "/",
            query=parse_qs(environ.get("QUERY_STRING", "")),
            headers=headers,
            cookies=cookies,
            body=body,
            remote_addr=remote or "0.0.0.0",
            environ=environ,
        )

    # --- accessors ---------------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return values[0] if values else default

    def get_all(self, name: str) -> list[str]:
        return self.query.get(name, [])

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def is_json(self) -> bool:
        return self.content_type == "application/json"

    @property
    def wants_json(self) -> bool:
        return self.is_json or self.path.startswith("/api/") or "application/json" in self.headers.get("accept", "")

    def form(self) -> dict[str, list[str]]:
        if self.content_type != "application/x-www-form-urlencoded":
            return {}
        return parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True)

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def data(self) -> dict[str, Any]:
        """Merged body payload, whichever encoding the client used."""
        if self.is_json:
            return self.json()
        return {key: values[0] for key, values in self.form().items()}

    def data_list(self, name: str) -> list[str]:
        if self.is_json:
            value = self.json().get(name)
            if isinstance(value, list):
                return [str(item) for item in value]
            return [str(value)] if value not in (None, "") else []
        return self.form().get(name, [])

    def param(self, name: str, default: str = "") -> str:
        return self.params.get(name, default)

    def int_param(self, name: str, default: int = 0) -> int:
        try:
            return int(self.params.get(name, default))
        except (TypeError, ValueError):
            return default
