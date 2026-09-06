"""WSGI entry point.

``application`` is a plain PEP 3333 callable, so the same object runs under
``wsgiref`` in development and under gunicorn/uWSGI in production without a
code change (42).
"""

from __future__ import annotations

import logging
import mimetypes
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import get_settings
from .core.errors import AppError, NotFound
from .core.middleware import apply_security_headers, attach_session, enforce_csrf, enforce_rate_limit
from .core.request import Request
from .core.response import Response, file_response, json_response
from .core.router import Router

logger = logging.getLogger("fitness_platform")

STATIC_DIR = Path(__file__).parent / "static"


def build_router() -> Router:
    from .web.routes import (
        admin_content_routes,
        admin_ops_routes,
        admin_routes,
        app_routes,
        auth_routes,
        onboarding_routes,
        public,
        subscription_routes,
    )
    from .web.routes.api import admin_api, ai_api, content_api, meal_api, user_api

    router = Router()
    public.register(router)
    auth_routes.register(router)
    onboarding_routes.register(router)
    subscription_routes.register(router)
    # Admin first: its paths are literal, and the member area matches a wildcard
    # segment, so registering the wildcard first would shadow /admin/settings.
    admin_routes.register(router)
    admin_content_routes.register(router)
    admin_ops_routes.register(router)
    app_routes.register(router)
    ai_api.register(router)
    content_api.register(router)
    meal_api.register(router)
    user_api.register(router)
    admin_api.register(router)
    return router


def _serve_static(path: str) -> Response:
    relative = path[len("/static/") :]
    target = (STATIC_DIR / relative).resolve()
    if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
        raise NotFound()
    content_type, _ = mimetypes.guess_type(target.name)
    settings = get_settings()
    cache = 31536000 if settings.is_production else 0
    return file_response(target.read_bytes(), content_type or "application/octet-stream", cache_seconds=cache)


def _error_response(request: Request, error: AppError) -> Response:
    from .services.authorization import CrossPathAccess
    from .web.ui.pages_error import render_error_page

    if isinstance(error, CrossPathAccess) and not request.wants_json:
        from .core.response import redirect

        return redirect(f"/{error.path.url_segment}/dashboard")

    if request.wants_json:
        payload: dict[str, Any] = {"error": error.code, "message": error.message}
        if getattr(error, "errors", None):
            payload["fields"] = error.errors
        return json_response(payload, error.status)
    return render_error_page(request, error)


def application(environ: dict, start_response: Callable) -> Iterable[bytes]:
    request = Request.from_environ(environ)
    router = _ROUTER

    try:
        if request.path.startswith("/static/"):
            response = _serve_static(request.path)
        else:
            enforce_rate_limit(request)
            attach_session(request)
            enforce_csrf(request)
            handler, params = router.resolve(request.method, request.path)
            request.params = params
            response = handler(request)
    except AppError as error:
        response = _error_response(request, error)
    except Exception:  # pragma: no cover - unexpected failure
        logger.error("unhandled error on %s %s\n%s", request.method, request.path, traceback.format_exc())
        response = _error_response(request, AppError())

    response = apply_security_headers(response, request).finalize()
    if request.method == "HEAD":
        response.body = b""
    start_response(response.status_line, response.headers)
    return [response.body]


_ROUTER = None


def create_app() -> Callable:
    """Build the router once and hand back the WSGI callable."""
    global _ROUTER
    logging.basicConfig(
        level=logging.DEBUG if get_settings().debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _ROUTER = build_router()
    return application
