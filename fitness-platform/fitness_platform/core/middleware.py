"""Cross-cutting request handling: headers, sessions, CSRF and rate limits (34)."""

from __future__ import annotations

from ..config import get_settings
from ..services.auth import SESSION_COOKIE, load_context
from ..services.security import constant_time_equals, limiter
from .errors import Forbidden, RateLimited
from .request import Request
from .response import Response

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Endpoints called by an external service rather than by a browser. Their
# authenticity comes from a provider signature checked inside the handler, so a
# CSRF token is neither available nor meaningful here (45).
CSRF_EXEMPT_PREFIXES = ("/api/payments/webhook",)

# A strict policy is possible because the app ships no third-party script and no
# inline handler: every script and style is served from this origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def attach_session(request: Request) -> None:
    session_id = request.cookies.get(SESSION_COOKIE, "")
    context = load_context(session_id) if session_id else None
    request.session = session_id if context else ""
    request.user = context
    if context:
        from ..db.repositories import users as users_repo

        users_repo.touch_last_active(context.user.id)
        from ..db.repositories.users import get_session

        stored = get_session(session_id)
        request.csrf_token = stored["csrf_token"] if stored else ""


def enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    key = f"req:{request.remote_addr}"
    if not limiter.check(key, settings.rate_limit_per_minute):
        raise RateLimited()


def enforce_csrf(request: Request) -> None:
    """Double-submit check on every state-changing request.

    The session cookie is ``SameSite=Lax``, which already blocks the common
    cross-site POST; the token is the second lock, and it is compared in
    constant time.
    """
    if request.method in SAFE_METHODS:
        return
    if request.path.startswith(CSRF_EXEMPT_PREFIXES):
        return
    if not request.session:
        # Anonymous POSTs (login, signup) are protected by SameSite plus the
        # origin check below; there is no session token to compare yet.
        _check_origin(request)
        return
    submitted = ""
    if request.is_json:
        submitted = str(request.json().get("csrf_token", ""))
    else:
        values = request.form().get("csrf_token", [])
        submitted = values[0] if values else ""
    if not submitted:
        submitted = request.headers.get("x-csrf-token", "")
    if not constant_time_equals(submitted, request.csrf_token):
        raise Forbidden("פג תוקף הטופס. רעננו את הדף ונסו שוב.", code="csrf")


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if not origin:
        return
    host = request.headers.get("host", "")
    if host and not origin.endswith(f"//{host}"):
        raise Forbidden("בקשה ממקור לא מזוהה.", code="origin")


def apply_security_headers(response: Response, request: Request) -> Response:
    settings = get_settings()
    response.set_header("X-Content-Type-Options", "nosniff")
    response.set_header("X-Frame-Options", "DENY")
    response.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
    response.set_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.set_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if settings.is_production:
        response.set_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not request.path.startswith("/static/"):
        response.set_header("Cache-Control", "no-store")
    return response
