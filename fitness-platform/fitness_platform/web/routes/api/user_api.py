"""Member self-service endpoints (43, 47).

Every handler resolves the member from the session and checks row ownership
before it touches anything — an id in the URL is a claim, not a permission.
"""

from __future__ import annotations

from ....core.errors import NotFound
from ....core.request import Request
from ....core.response import Response, json_response
from ....core.router import Router
from ....db.repositories import food as food_repo
from ....services.authorization import require_owner, require_user


def me(request: Request) -> Response:
    ctx = require_user(request)
    return json_response(
        {
            "id": ctx.user.id,
            "name": ctx.user.name,
            "email": ctx.user.email,
            "role": ctx.user.role.value,
            "gender_path": ctx.user.gender_path.value if ctx.user.gender_path else None,
            "onboarding_completed": ctx.user.onboarding_completed,
            "subscription": {
                "status": ctx.subscription.status.value if ctx.subscription else None,
                "active": ctx.has_active_subscription,
            },
        }
    )


def toggle_shopping_item(request: Request) -> Response:
    ctx = require_user(request)
    item_id = request.int_param("item_id")
    owner = food_repo.shopping_item_owner(item_id)
    if owner is None:
        raise NotFound()
    require_owner(ctx, owner)
    checked = bool(request.data().get("checked"))
    food_repo.toggle_shopping_item(item_id, checked)
    return json_response({"id": item_id, "checked": checked})


def delete_shopping_item(request: Request) -> Response:
    ctx = require_user(request)
    item_id = request.int_param("item_id")
    owner = food_repo.shopping_item_owner(item_id)
    if owner is None:
        raise NotFound()
    require_owner(ctx, owner)
    food_repo.delete_shopping_item(item_id)
    return json_response({"deleted": item_id})


def add_shopping_item(request: Request) -> Response:
    ctx = require_user(request)
    data = request.data()
    name = str(data.get("name", "")).strip()
    if not name:
        raise NotFound()
    list_id = food_repo.get_or_create_shopping_list(ctx.user.id)
    require_owner(ctx, food_repo.shopping_list_owner(list_id))
    item_id = food_repo.add_shopping_item(list_id, name, str(data.get("amount", "")))
    return json_response({"id": item_id, "name": name}, 201)


def register(router: Router) -> None:
    router.get("/api/users/me", me)
    router.post("/api/shopping/items", add_shopping_item)
    router.post("/api/shopping/items/<int:item_id>/toggle", toggle_shopping_item)
    router.post("/api/shopping/items/<int:item_id>/delete", delete_shopping_item)
