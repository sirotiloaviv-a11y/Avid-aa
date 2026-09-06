"""AI endpoints (43).

Authorisation happens before anything is read: the handler resolves the member
from the session, and the coach service only ever sees that member's context.
"""

from __future__ import annotations

from ....core.errors import BadRequest, PaymentRequired
from ....core.request import Request
from ....core.response import Response, json_response
from ....core.router import Router
from ....services.ai import coach as coach_service
from ....services.authorization import require_user


def coach_message(request: Request) -> Response:
    ctx = require_user(request)
    if ctx.user.gender_path is None:
        raise BadRequest("צריך לבחור מסלול.")
    if not ctx.has_active_subscription:
        raise PaymentRequired()

    question = str(request.data().get("question", "")).strip()
    if not question:
        raise BadRequest("לא התקבלה שאלה.")

    reply = coach_service.ask(ctx, question)
    return json_response({"answer": reply.text, "status": reply.status})


def coach_history(request: Request) -> Response:
    ctx = require_user(request)
    if ctx.user.gender_path is None:
        raise BadRequest("צריך לבחור מסלול.")
    messages = coach_service.history(ctx)
    return json_response(
        {"messages": [{"role": message["role"], "content": message["content"]} for message in messages]}
    )


def register(router: Router) -> None:
    router.post("/api/ai/coach", coach_message)
    router.get("/api/ai/history", coach_history)
