"""Friendly error pages (39)."""

from __future__ import annotations

from ...core.errors import AppError
from ...core.request import Request
from ...core.response import Response, html
from .components import button, empty_state
from .layouts import public_layout
from .primitives import esc

_TITLES = {
    400: "בקשה לא תקינה",
    401: "צריך להתחבר",
    403: "אין גישה",
    404: "הדף לא נמצא",
    405: "פעולה לא נתמכת",
    429: "רגע אחד",
    500: "תקלה זמנית",
}


def render_error_page(request: Request, error: AppError) -> Response:
    title = _TITLES.get(error.status, "שגיאה")
    if error.status == 401:
        action = button("להתחברות", href=f"/login?next={esc(request.path)}", variant="primary")
    elif error.status == 403 and error.code == "payment_required":
        action = button("לבחירת מנוי", href="/subscribe", variant="primary")
    elif error.status == 403 and error.code == "path_missing":
        action = button("לבחירת מסלול", href="/start", variant="primary")
    else:
        action = button("חזרה לדף הבית", href="/", variant="secondary")

    body = f"""
    <div class="container narrow error-page">
      <span class="error-code">{error.status}</span>
      {empty_state(title, error.message, icon_name="shield", action=action)}
    </div>
    """
    return html(public_layout(body, title=title, show_nav=False), status=error.status)
