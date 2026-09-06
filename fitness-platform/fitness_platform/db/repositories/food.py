"""Recipes, meal plans and shopping lists (19, 20, 27)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ...domain.gender import GenderPath, scope_sql
from ...domain.models import Recipe
from ..connection import execute, query, query_one, transaction
from ..json_fields import dumps

MEAL_TYPES: tuple[tuple[str, str], ...] = (
    ("breakfast", "ארוחת בוקר"),
    ("lunch", "ארוחת צהריים"),
    ("dinner", "ארוחת ערב"),
    ("snack", "נשנוש"),
)
MEAL_TYPE_LABELS = dict(MEAL_TYPES)

DIETARY_TAGS: tuple[tuple[str, str], ...] = (
    ("vegetarian", "צמחוני"),
    ("vegan", "טבעוני"),
    ("gluten_free", "ללא גלוטן"),
    ("dairy_free", "ללא חלב"),
    ("high_protein", "עתיר חלבון"),
    ("kosher", "כשר"),
)
DIETARY_LABELS = dict(DIETARY_TAGS)

ALLERGENS: tuple[tuple[str, str], ...] = (
    ("nuts", "אגוזים"),
    ("peanuts", "בוטנים"),
    ("dairy", "חלב"),
    ("eggs", "ביצים"),
    ("gluten", "גלוטן"),
    ("fish", "דגים"),
    ("soy", "סויה"),
    ("sesame", "שומשום"),
)
ALLERGEN_LABELS = dict(ALLERGENS)

SHOPPING_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("produce", "פירות וירקות"),
    ("protein", "חלבונים"),
    ("dairy", "מוצרי חלב"),
    ("pantry", "מזווה"),
    ("other", "שונות"),
)
SHOPPING_CATEGORY_LABELS = dict(SHOPPING_CATEGORIES)


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ---------------------------------------------------------------- recipes ---
def list_recipes(
    path: GenderPath,
    *,
    meal_type: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[Recipe]:
    scope_clause, params = scope_sql(path)
    clauses = [scope_clause, "approved = 1"]
    if meal_type:
        clauses.append("meal_type = ?")
        params.append(meal_type)
    if search:
        clauses.append("(name LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    params.extend([limit, offset])
    return [
        Recipe.from_row(row)
        for row in query(
            f"SELECT * FROM recipes WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ? OFFSET ?",
            params,
        )
    ]


def get_recipe(recipe_id: int, path: GenderPath | None = None) -> Recipe | None:
    clauses, params = ["id = ?"], [recipe_id]
    if path is not None:
        scope_clause, scope_params = scope_sql(path)
        clauses.extend([scope_clause, "approved = 1"])
        params.extend(scope_params)
    return Recipe.from_row(query_one(f"SELECT * FROM recipes WHERE {' AND '.join(clauses)}", params))


def create_recipe(**fields: Any) -> int:
    return execute(
        """
        INSERT INTO recipes (name, description, ingredients, instructions, image_url, tags,
                             meal_type, dietary_tags, allergens, gender_path, prep_minutes,
                             approved, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields.get("name", ""),
            fields.get("description", ""),
            dumps(fields.get("ingredients", [])),
            dumps(fields.get("instructions", [])),
            fields.get("image_url", ""),
            dumps(fields.get("tags", [])),
            fields.get("meal_type", "lunch"),
            dumps(fields.get("dietary_tags", [])),
            dumps(fields.get("allergens", [])),
            fields.get("gender_path", "all"),
            int(fields.get("prep_minutes") or 15),
            1 if fields.get("approved") else 0,
            _now(),
            _now(),
        ),
    )


_RECIPE_WRITABLE = {"name", "description", "image_url", "meal_type", "gender_path", "prep_minutes", "approved"}
_RECIPE_JSON = {"ingredients", "instructions", "tags", "dietary_tags", "allergens"}


def update_recipe(recipe_id: int, **fields: Any) -> None:
    updates = {k: v for k, v in fields.items() if k in _RECIPE_WRITABLE or k in _RECIPE_JSON}
    if not updates:
        return
    assignments, params = [], []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        params.append(dumps(value) if key in _RECIPE_JSON else value)
    params.extend([_now(), recipe_id])
    execute(f"UPDATE recipes SET {', '.join(assignments)}, updated_at = ? WHERE id = ?", params)


def delete_recipe(recipe_id: int) -> None:
    execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))


def admin_list_recipes(
    *, gender_path: str = "", meal_type: str = "", approved: str = "", search: str = "",
    limit: int = 100, offset: int = 0,
) -> list[Recipe]:
    clauses, params = ["1 = 1"], []
    if gender_path:
        clauses.append("gender_path = ?")
        params.append(gender_path)
    if meal_type:
        clauses.append("meal_type = ?")
        params.append(meal_type)
    if approved in ("0", "1"):
        clauses.append("approved = ?")
        params.append(int(approved))
    if search:
        clauses.append("name LIKE ?")
        params.append(f"%{search}%")
    params.extend([limit, offset])
    return [
        Recipe.from_row(row)
        for row in query(
            f"SELECT * FROM recipes WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        )
    ]


# ------------------------------------------------------------- meal plans ---
def get_or_create_meal_plan(user_id: int, week_start: str) -> int:
    row = query_one(
        "SELECT id FROM meal_plans WHERE user_id = ? AND week_start = ?", (user_id, week_start)
    )
    if row:
        return int(row["id"])
    return execute(
        "INSERT INTO meal_plans (user_id, week_start, created_at) VALUES (?, ?, ?)",
        (user_id, week_start, _now()),
    )


def latest_meal_plan(user_id: int) -> dict[str, Any] | None:
    row = query_one(
        "SELECT * FROM meal_plans WHERE user_id = ? ORDER BY week_start DESC LIMIT 1", (user_id,)
    )
    return dict(row) if row else None


def replace_meal_plan_items(meal_plan_id: int, items: Iterable[tuple[int, int, str]]) -> None:
    """items = (recipe_id, day_index, meal_type)."""
    with transaction() as connection:
        connection.execute("DELETE FROM meal_plan_items WHERE meal_plan_id = ?", (meal_plan_id,))
        connection.executemany(
            "INSERT INTO meal_plan_items (meal_plan_id, recipe_id, day_index, meal_type) VALUES (?, ?, ?, ?)",
            [(meal_plan_id, recipe_id, day_index, meal_type) for recipe_id, day_index, meal_type in items],
        )


def set_meal_plan_item(meal_plan_id: int, day_index: int, meal_type: str, recipe_id: int) -> None:
    execute(
        """
        INSERT INTO meal_plan_items (meal_plan_id, recipe_id, day_index, meal_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (meal_plan_id, day_index, meal_type) DO UPDATE SET recipe_id = excluded.recipe_id
        """,
        (meal_plan_id, recipe_id, day_index, meal_type),
    )


def meal_plan_items(meal_plan_id: int, path: GenderPath) -> list[dict[str, Any]]:
    """Join through to recipes, still scoped by path — a stale plan row that
    points at content from the other path is filtered out rather than shown."""
    scope_clause, scope_params = scope_sql(path, "r.gender_path")
    rows = query(
        f"""
        SELECT i.day_index, i.meal_type, r.*
          FROM meal_plan_items i
          JOIN recipes r ON r.id = i.recipe_id
         WHERE i.meal_plan_id = ? AND {scope_clause} AND r.approved = 1
         ORDER BY i.day_index, CASE i.meal_type
                    WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1
                    WHEN 'dinner' THEN 2 ELSE 3 END
        """,
        [meal_plan_id, *scope_params],
    )
    return [
        {"day_index": int(row["day_index"]), "meal_type": row["meal_type"], "recipe": Recipe.from_row(row)}
        for row in rows
    ]


def meal_plan_owner(meal_plan_id: int) -> int | None:
    row = query_one("SELECT user_id FROM meal_plans WHERE id = ?", (meal_plan_id,))
    return int(row["user_id"]) if row else None


# --------------------------------------------------------- shopping lists ---
def get_or_create_shopping_list(user_id: int, meal_plan_id: int | None = None) -> int:
    row = query_one(
        "SELECT id FROM shopping_lists WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
    )
    if row:
        return int(row["id"])
    return execute(
        "INSERT INTO shopping_lists (user_id, meal_plan_id, created_at) VALUES (?, ?, ?)",
        (user_id, meal_plan_id, _now()),
    )


def shopping_list_owner(list_id: int) -> int | None:
    row = query_one("SELECT user_id FROM shopping_lists WHERE id = ?", (list_id,))
    return int(row["user_id"]) if row else None


def shopping_item_owner(item_id: int) -> int | None:
    row = query_one(
        """
        SELECT l.user_id FROM shopping_list_items i
          JOIN shopping_lists l ON l.id = i.shopping_list_id
         WHERE i.id = ?
        """,
        (item_id,),
    )
    return int(row["user_id"]) if row else None


def list_shopping_items(list_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query(
            "SELECT * FROM shopping_list_items WHERE shopping_list_id = ? ORDER BY category, name",
            (list_id,),
        )
    ]


def add_shopping_item(list_id: int, name: str, amount: str = "", category: str = "other") -> int:
    return execute(
        "INSERT INTO shopping_list_items (shopping_list_id, name, amount, category) VALUES (?, ?, ?, ?)",
        (list_id, name.strip()[:120], amount.strip()[:60], category),
    )


def replace_shopping_items(list_id: int, items: Iterable[dict[str, str]]) -> None:
    with transaction() as connection:
        connection.execute(
            "DELETE FROM shopping_list_items WHERE shopping_list_id = ? AND checked = 0", (list_id,)
        )
        connection.executemany(
            "INSERT INTO shopping_list_items (shopping_list_id, name, amount, category) VALUES (?, ?, ?, ?)",
            [
                (list_id, item["name"][:120], item.get("amount", "")[:60], item.get("category", "other"))
                for item in items
            ],
        )


def toggle_shopping_item(item_id: int, checked: bool) -> None:
    execute("UPDATE shopping_list_items SET checked = ? WHERE id = ?", (1 if checked else 0, item_id))


def delete_shopping_item(item_id: int) -> None:
    execute("DELETE FROM shopping_list_items WHERE id = ?", (item_id,))


def clear_checked_items(list_id: int) -> None:
    execute("DELETE FROM shopping_list_items WHERE shopping_list_id = ? AND checked = 1", (list_id,))
