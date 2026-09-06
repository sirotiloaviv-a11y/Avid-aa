"""A small path router with typed segment parameters.

Routes are registered as ``/women/workouts/<int:video_id>``. The router matches
in registration order and returns the handler plus extracted params. Anything
more clever would be a framework, and a framework is what we are deliberately
not depending on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .errors import MethodNotAllowed, NotFound
from .request import Request
from .response import Response

Handler = Callable[[Request], Response]

_SEGMENT = re.compile(r"<(?:(?P<type>int|str|slug):)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")
_TYPE_PATTERNS = {
    "int": r"[0-9]+",
    "str": r"[^/]+",
    "slug": r"[a-zA-Z0-9_-]+",
}


def _compile(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    for match in _SEGMENT.finditer(pattern):
        parts.append(re.escape(pattern[index : match.start()]))
        kind = match.group("type") or "str"
        parts.append(f"(?P<{match.group('name')}>{_TYPE_PATTERNS[kind]})")
        index = match.end()
    parts.append(re.escape(pattern[index:]))
    return re.compile("^" + "".join(parts) + "$")


@dataclass(frozen=True)
class Route:
    methods: frozenset[str]
    pattern: str
    regex: re.Pattern[str]
    handler: Handler
    name: str


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(
        self,
        methods: Iterable[str] | str,
        pattern: str,
        handler: Handler,
        *,
        name: str = "",
    ) -> None:
        if isinstance(methods, str):
            methods = [methods]
        method_set = frozenset(method.upper() for method in methods)
        if "GET" in method_set:
            method_set = method_set | {"HEAD"}
        self._routes.append(
            Route(method_set, pattern, _compile(pattern), handler, name or handler.__name__)
        )

    def get(self, pattern: str, handler: Handler, **kwargs) -> None:
        self.add("GET", pattern, handler, **kwargs)

    def post(self, pattern: str, handler: Handler, **kwargs) -> None:
        self.add("POST", pattern, handler, **kwargs)

    def route(self, methods: Iterable[str] | str, pattern: str, **kwargs):
        def decorator(handler: Handler) -> Handler:
            self.add(methods, pattern, handler, **kwargs)
            return handler

        return decorator

    def include(self, other: "Router", prefix: str = "") -> None:
        for route in other._routes:
            self.add(
                route.methods - {"HEAD"},
                prefix + route.pattern,
                route.handler,
                name=route.name,
            )

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str]]:
        allowed: set[str] = set()
        for route in self._routes:
            match = route.regex.match(path)
            if not match:
                continue
            if method not in route.methods:
                allowed |= route.methods
                continue
            return route.handler, {k: v for k, v in match.groupdict().items() if v is not None}
        if allowed:
            raise MethodNotAllowed()
        raise NotFound()

    @property
    def routes(self) -> list[Route]:
        return list(self._routes)
