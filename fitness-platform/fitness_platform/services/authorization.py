"""Route and API guards — the one place access decisions are made (2, 34, 46).

Guards read identity from the server-side session, never from the URL, a form
field or a cookie the client can write. A ``/women/...`` URL does not make a
request female; the session's ``gender_path`` does, and if the two disagree the
request is rejected.
"""

from __future__ import annotations

from ..core.errors import Forbidden, PaymentRequired, Unauthorized
from ..core.request import Request
from ..db.repositories import insights
from ..domain.gender import GenderPath, can_view
from ..domain.models import AuthContext
from ..domain.roles import Permission, has_permission


class CrossPathAccess(Forbidden):
    """A user tried to open the other path's area.

    Carried as its own type so the HTML layer can bounce the user back to their
    own dashboard while the API layer answers a plain 403.
    """

    code = "cross_path"
    message = "האזור הזה שייך למסלול אחר."

    def __init__(self, path: GenderPath):
        super().__init__()
        self.path = path


def context(request: Request) -> AuthContext | None:
    return request.user if isinstance(request.user, AuthContext) else None


def require_user(request: Request) -> AuthContext:
    ctx = context(request)
    if ctx is None:
        raise Unauthorized()
    return ctx


def require_admin(request: Request) -> AuthContext:
    ctx = require_user(request)
    if not has_permission(ctx.user.role, Permission.MANAGE_USERS):
        _record_denial(ctx, request, "admin_area")
        raise Forbidden()
    return ctx


def require_permission(request: Request, permission: Permission) -> AuthContext:
    ctx = require_user(request)
    if not has_permission(ctx.user.role, permission):
        _record_denial(ctx, request, permission.value)
        raise Forbidden()
    return ctx


def require_path(request: Request, segment: str) -> AuthContext:
    """Authorise a request for the ``/women`` or ``/men`` area.

    ``segment`` comes from the URL. The user's own path comes from the session.
    They must agree; an admin browsing a user-facing area is treated the same
    way, because the admin product area is ``/admin`` and mixing them would put
    an admin inside a member's personalised content (46).
    """
    ctx = require_user(request)
    requested = GenderPath.from_url_segment(segment)
    if requested is None:
        raise Forbidden()
    own = ctx.user.gender_path
    if own is None:
        # Signed up but never picked a path: send them through selection.
        raise Forbidden("צריך לבחור מסלול לפני הכניסה לאזור האישי.", code="path_missing")
    if own is not requested:
        _record_denial(ctx, request, f"cross_path:{segment}")
        raise CrossPathAccess(own)
    return ctx


def require_active_subscription(request: Request, segment: str) -> AuthContext:
    ctx = require_path(request, segment)
    if not ctx.has_active_subscription:
        raise PaymentRequired()
    return ctx


def require_content_access(ctx: AuthContext, scope: object) -> None:
    """Final check before rendering a content row (14, 53)."""
    if not can_view(ctx.user.gender_path, scope):
        raise Forbidden()


def require_owner(ctx: AuthContext, owner_id: int | None) -> None:
    """Reject reading or writing another member's row (47)."""
    if owner_id is None or owner_id != ctx.user.id:
        raise Forbidden()


def _record_denial(ctx: AuthContext, request: Request, reason: str) -> None:
    try:
        insights.record_audit(
            ctx.user.id,
            "access_denied",
            entity_type="route",
            entity_id=request.path,
            details={"reason": reason, "role": ctx.user.role.value},
            ip_address=request.remote_addr,
        )
    except Exception:  # pragma: no cover - never let logging break a 403
        pass
