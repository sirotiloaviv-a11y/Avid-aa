"""Response objects and the small set of helpers routes use to build them."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Iterable

STATUS_TEXT = {
    200: "OK",
    201: "Created",
    204: "No Content",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
}


@dataclass
class Response:
    body: bytes = b""
    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=list)

    @property
    def status_line(self) -> str:
        return f"{self.status} {STATUS_TEXT.get(self.status, 'Unknown')}"

    def set_header(self, name: str, value: str) -> "Response":
        lowered = name.lower()
        self.headers = [(key, val) for key, val in self.headers if key.lower() != lowered]
        self.headers.append((name, value))
        return self

    def add_header(self, name: str, value: str) -> "Response":
        self.headers.append((name, value))
        return self

    def set_cookie(
        self,
        name: str,
        value: str,
        *,
        max_age: int | None = None,
        http_only: bool = True,
        secure: bool = False,
        same_site: str = "Lax",
        path: str = "/",
    ) -> "Response":
        jar = SimpleCookie()
        jar[name] = value
        morsel = jar[name]
        morsel["path"] = path
        if max_age is not None:
            morsel["max-age"] = str(max_age)
        if http_only:
            morsel["httponly"] = True
        if secure:
            morsel["secure"] = True
        cookie = morsel.OutputString()
        if same_site:
            cookie += f"; SameSite={same_site}"
        return self.add_header("Set-Cookie", cookie)

    def delete_cookie(self, name: str, path: str = "/") -> "Response":
        return self.add_header(
            "Set-Cookie", f"{name}=; Path={path}; Max-Age=0; HttpOnly; SameSite=Lax"
        )

    def finalize(self) -> "Response":
        if not any(key.lower() == "content-length" for key, _ in self.headers):
            self.set_header("Content-Length", str(len(self.body)))
        return self


def html(markup: str, status: int = 200) -> Response:
    return Response(
        markup.encode("utf-8"),
        status,
        [("Content-Type", "text/html; charset=utf-8")],
    )


def json_response(payload: Any, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        status,
        [("Content-Type", "application/json; charset=utf-8")],
    )


def text(body: str, status: int = 200) -> Response:
    return Response(body.encode("utf-8"), status, [("Content-Type", "text/plain; charset=utf-8")])


def redirect(location: str, status: int = 303) -> Response:
    return Response(b"", status, [("Location", location)])


def no_content() -> Response:
    return Response(b"", 204, [])


def file_response(data: bytes, content_type: str, *, cache_seconds: int = 0) -> Response:
    response = Response(data, 200, [("Content-Type", content_type)])
    if cache_seconds:
        response.set_header("Cache-Control", f"public, max-age={cache_seconds}")
    return response


def stream_bytes(chunks: Iterable[bytes]) -> bytes:
    return b"".join(chunks)
