"""Meal plan endpoints (20, 43)."""

from __future__ import annotations

from ....core.errors import BadRequest, NotFound, PaymentRequired
from ....core.request import Request
from ....core.response import Response, json_response
from ....core.router import Router
from ....db.repositories import food as food_repo
from ....services import analytics, meal_service
from ....services.authorization import require_owner, require_user


def _member(request: Request):
    ctx = require_user(request)
    if ctx.user.gender_path is None or not ctx.has_active_subscription:
        raise PaymentRequired()
    return ctx, ctx.user.gender_path


def current_plan(request: Request) -> Response:
    ctx, path = _member(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    grouped = meal_service.plan_days(plan_id, path)
    return json_response(
        {
            "plan_id": plan_id,
            "days": {
                str(day): [
                    {
                        "meal_type": item["meal_type"],
                        "recipe": {"id": item["recipe"].id, "name": item["recipe"].name},
                    }
                    for item in items
                ]
                for day, items in grouped.items()
            },
        }
    )


def replace_meal(request: Request) -> Response:
    ctx, path = _member(request)
    data = request.data()
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    require_owner(ctx, food_repo.meal_plan_owner(plan_id))
    try:
        day_index = int(data.get("day_index", -1))
        recipe_id = int(data.get("recipe_id", 0))
    except (TypeError, ValueError):
        raise BadRequest("פרמטרים לא תקינים.")
    if not 0 <= day_index <= 6:
        raise BadRequest("יום לא תקין.")
    meal_type = str(data.get("meal_type", ""))
    replacement = meal_service.replace_meal(plan_id, ctx.profile, path, day_index, meal_type, recipe_id)
    if replacement is None:
        raise NotFound("לא נמצאה חלופה מתאימה.")
    analytics.track(analytics.MEAL_REPLACED, user_id=ctx.user.id, gender_path=path.value)
    return json_response({"recipe": {"id": replacement.id, "name": replacement.name}})


def shopping_list(request: Request) -> Response:
    ctx, path = _member(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    list_id = food_repo.get_or_create_shopping_list(ctx.user.id, plan_id)
    return json_response({"list_id": list_id, "items": food_repo.list_shopping_items(list_id)})


def build_shopping_list(request: Request) -> Response:
    ctx, path = _member(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    list_id = meal_service.build_shopping_list(ctx.user.id, plan_id, path)
    return json_response({"list_id": list_id, "items": food_repo.list_shopping_items(list_id)}, 201)


def register(router: Router) -> None:
    router.get("/api/meal-plans/current", current_plan)
    router.post("/api/meal-plans/replace", replace_meal)
    router.get("/api/shopping-lists/current", shopping_list)
    router.post("/api/shopping-lists/build", build_shopping_list)
