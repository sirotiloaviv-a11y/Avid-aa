"""Meal plans and shopping lists (19, 20).

The AI never invents a dish. The plan is assembled from approved recipes that
survive the rules engine's hard filters (allergies, dietary rules, dislikes),
and the shopping list is derived from the plan.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..db.repositories import food as food_repo
from ..domain.gender import GenderPath
from ..domain.models import Profile, Recipe
from ..domain.rules_engine import assert_scope, rank_recipes

MEALS_BY_COUNT = {
    3: ("breakfast", "lunch", "dinner"),
    4: ("breakfast", "lunch", "dinner", "snack"),
    5: ("breakfast", "snack", "lunch", "snack", "dinner"),
}

_CATEGORY_HINTS = {
    "produce": ("עגבני", "מלפפון", "בצל", "פלפל", "תרד", "חסה", "לימון", "בננה", "תפוח", "אבוקדו", "גזר", "בטטה", "ברוקולי", "קישוא", "תות"),
    "protein": ("עוף", "חזה", "בקר", "טונה", "סלמון", "ביצ", "טופו", "עדשים", "חומוס", "קטנ"),
    "dairy": ("יוגורט", "גבינ", "חלב", "קוטג"),
    "pantry": ("שמן", "אורז", "קינואה", "שיבולת", "קמח", "טחינה", "אגוז", "שקד", "דבש", "תבלין", "מלח", "פסטה"),
}


def week_start_for(day: date | None = None) -> str:
    current = day or date.today()
    start = current - timedelta(days=(current.weekday() + 1) % 7)
    return start.isoformat()


def _slots(profile: Profile) -> tuple[str, ...]:
    return MEALS_BY_COUNT.get(profile.meals_per_day, MEALS_BY_COUNT[3])


def eligible_recipes(profile: Profile, path: GenderPath, meal_type: str) -> list[Recipe]:
    candidates = food_repo.list_recipes(path, meal_type=meal_type, limit=100)
    return assert_scope(path, rank_recipes(profile, candidates))


def generate_plan(user_id: int, profile: Profile, path: GenderPath, *, week_start: str | None = None) -> int:
    """Build (or rebuild) a seven-day plan and return the meal plan id."""
    week = week_start or week_start_for()
    plan_id = food_repo.get_or_create_meal_plan(user_id, week)

    items: list[tuple[int, int, str]] = []
    for meal_type in dict.fromkeys(_slots(profile)):
        pool = eligible_recipes(profile, path, meal_type)
        if not pool:
            continue
        for day_index in range(7):
            recipe = pool[day_index % len(pool)]
            items.append((recipe.id, day_index, meal_type))
    food_repo.replace_meal_plan_items(plan_id, items)
    return plan_id


def ensure_plan(user_id: int, profile: Profile, path: GenderPath) -> int:
    week = week_start_for()
    existing = food_repo.latest_meal_plan(user_id)
    if existing and existing.get("week_start") == week:
        plan_id = int(existing["id"])
        if food_repo.meal_plan_items(plan_id, path):
            return plan_id
    return generate_plan(user_id, profile, path, week_start=week)


def plan_days(plan_id: int, path: GenderPath) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {index: [] for index in range(7)}
    for item in food_repo.meal_plan_items(plan_id, path):
        grouped.setdefault(item["day_index"], []).append(item)
    return grouped


def today_index() -> int:
    return (date.today().weekday() + 1) % 7


def todays_meals(plan_id: int, path: GenderPath) -> list[dict]:
    return plan_days(plan_id, path).get(today_index(), [])


def replace_meal(
    plan_id: int, profile: Profile, path: GenderPath, day_index: int, meal_type: str, current_recipe_id: int
) -> Recipe | None:
    """Swap one slot for the next eligible recipe (20)."""
    pool = eligible_recipes(profile, path, meal_type)
    if not pool:
        return None
    ids = [recipe.id for recipe in pool]
    if current_recipe_id in ids and len(pool) > 1:
        next_index = (ids.index(current_recipe_id) + 1) % len(pool)
    else:
        next_index = 0
    replacement = pool[next_index]
    food_repo.set_meal_plan_item(plan_id, day_index, meal_type, replacement.id)
    return replacement


def _categorise(name: str) -> str:
    for category, hints in _CATEGORY_HINTS.items():
        if any(hint in name for hint in hints):
            return category
    return "other"


def build_shopping_list(user_id: int, plan_id: int, path: GenderPath, *, days: int = 7) -> int:
    """Roll the plan's ingredients up into a list, merging duplicates."""
    list_id = food_repo.get_or_create_shopping_list(user_id, plan_id)
    totals: dict[str, dict[str, str]] = {}
    for item in food_repo.meal_plan_items(plan_id, path):
        if item["day_index"] >= days:
            continue
        recipe = item["recipe"]
        for ingredient in recipe.ingredients or []:
            name = str(ingredient.get("name", "")).strip()
            if not name:
                continue
            amount = str(ingredient.get("amount", "")).strip()
            unit = str(ingredient.get("unit", "")).strip()
            entry = totals.setdefault(
                name, {"name": name, "amount": "", "category": _categorise(name), "count": 0}
            )
            entry["count"] = int(entry["count"]) + 1
            if amount and not entry["amount"]:
                entry["amount"] = f"{amount} {unit}".strip()

    rows = []
    for entry in totals.values():
        count = int(entry.pop("count"))
        if count > 1:
            entry["amount"] = (entry["amount"] + f" ×{count}").strip()
        rows.append(entry)
    food_repo.replace_shopping_items(list_id, rows)
    return list_id


def shopping_items_by_category(list_id: int) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in food_repo.list_shopping_items(list_id):
        grouped.setdefault(item["category"], []).append(item)
    return grouped
