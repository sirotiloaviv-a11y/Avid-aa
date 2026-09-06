"""Admin JSON endpoints (43, 46).

Same guard as the admin pages. These exist for the parts of the console that
benefit from acting without a page reload, and for operational checks.
"""

from __future__ import annotations

from ....config import get_settings
from ....core.errors import NotFound
from ....core.request import Request
from ....core.response import Response, json_response
from ....core.router import Router
from ....db.repositories import (
    ai as ai_repo,
    billing as billing_repo,
    content as content_repo,
    food as food_repo,
    insights,
    users as users_repo,
)
from ....services.ai.factory import get_provider as get_ai_provider
from ....services.authorization import require_admin
from ....services.payments.factory import get_provider as get_payment_provider
from ....services.storage.factory import get_provider as get_storage_provider


def stats(request: Request) -> Response:
    require_admin(request)
    distribution = users_repo.gender_distribution()
    return json_response(
        {
            "users": {
                "total": users_repo.count_users(),
                "female": distribution.get("female", 0),
                "male": distribution.get("male", 0),
                "active_7d": users_repo.active_user_count(7),
            },
            "subscriptions": billing_repo.subscription_breakdown(),
            "revenue_30d_cents": billing_repo.revenue_cents(30),
            "ai": ai_repo.usage_stats(30),
        }
    )


def toggle_video_publish(request: Request) -> Response:
    ctx = require_admin(request)
    video_id = request.int_param("video_id")
    video = content_repo.get_video(video_id)
    if video is None:
        raise NotFound()
    published = not video.published
    content_repo.update_video(video_id, published=1 if published else 0)
    insights.record_audit(
        ctx.user.id, "video_publish_toggled", entity_type="video", entity_id=str(video_id),
        details={"published": published}, ip_address=request.remote_addr,
    )
    return json_response({"id": video_id, "published": published})


def toggle_recipe_approval(request: Request) -> Response:
    ctx = require_admin(request)
    recipe_id = request.int_param("recipe_id")
    recipe = food_repo.get_recipe(recipe_id)
    if recipe is None:
        raise NotFound()
    approved = not recipe.approved
    food_repo.update_recipe(recipe_id, approved=1 if approved else 0)
    insights.record_audit(
        ctx.user.id, "recipe_approval_toggled", entity_type="recipe", entity_id=str(recipe_id),
        details={"approved": approved}, ip_address=request.remote_addr,
    )
    return json_response({"id": recipe_id, "approved": approved})


def health(request: Request) -> Response:
    """Operational check. Reports which providers are live and which are mocks
    so a deploy cannot quietly go out with the mock payment provider (50)."""
    require_admin(request)
    settings = get_settings()
    return json_response(
        {
            "env": settings.env,
            "mode": settings.mode,
            "ai": get_ai_provider().health(),
            "payments": get_payment_provider().health(),
            "storage": get_storage_provider().health(),
        }
    )


def register(router: Router) -> None:
    router.get("/api/admin/stats", stats)
    router.get("/api/admin/health", health)
    router.post("/api/admin/videos/<int:video_id>/publish", toggle_video_publish)
    router.post("/api/admin/recipes/<int:recipe_id>/approve", toggle_recipe_approval)
