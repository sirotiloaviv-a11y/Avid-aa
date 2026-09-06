"""Small helpers shared by route modules."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from ..core.request import Request
from ..core.response import Response, redirect
from ..domain.models import AuthContext


def flash_redirect(location: str, message: str = "", tone: str = "success") -> Response:
    """Redirect with a one-shot message. The client shows it as a toast and
    strips it from the URL, so nothing is stored server-side for it."""
    if message:
        separator = "&" if "?" in location else "?"
        location = f"{location}{separator}{urlencode({'flash': message, 'tone': tone})}"
    return redirect(location)


def safe_next(request: Request, fallback: str = "/") -> str:
    """Only ever redirect to a path on this origin (open-redirect guard)."""
    target = request.get("next") or request.data().get("next", "")
    if isinstance(target, str) and target.startswith("/") and not target.startswith("//"):
        return target
    return fallback


def home_for(context: AuthContext | None) -> str:
    """Where this user belongs after signing in (11)."""
    if context is None:
        return "/login"
    user = context.user
    if user.is_admin:
        return "/admin"
    if user.gender_path is None:
        return "/start"
    if not user.onboarding_completed:
        return "/onboarding"
    if not context.has_active_subscription:
        return "/subscribe"
    return f"/{user.gender_path.url_segment}/dashboard"


def login_redirect(request: Request) -> Response:
    return redirect(f"/login?next={quote(request.path)}")
