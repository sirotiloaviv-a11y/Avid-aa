"""Deterministic personalisation rules (18, 20).

The rules engine is the hard filter: it decides what a given profile is
*allowed* and *suited* to receive out of the approved library. The AI layer runs
after it and may only reorder or pick from what this module returns — it never
widens the candidate set, and it never invents an item.

Everything here is a pure function of (profile, candidate rows), which is what
makes the behaviour testable without a database or a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .gender import GenderPath, can_view
from .models import Profile, Recipe, Video

_LEVEL_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}

# Which goal keys favour which video categories.
_GOAL_CATEGORY_BONUS: dict[str, dict[str, int]] = {
    "tone": {"full_body": 3, "lower_body": 3, "core": 2},
    "strength": {"upper_body": 3, "full_body": 2, "lower_body": 2},
    "muscle": {"upper_body": 3, "lower_body": 3, "full_body": 2},
    "cut": {"full_body": 3, "short_workout": 2, "core": 2},
    "weight": {"full_body": 3, "short_workout": 2},
    "endurance": {"full_body": 2, "short_workout": 3},
    "posture": {"stretch": 3, "core": 2, "warmup": 1},
    "mobility": {"stretch": 3, "warmup": 2},
    "energy": {"short_workout": 3, "full_body": 1},
    "routine": {"short_workout": 2, "full_body": 1},
}

# Equipment the user does not have makes an item unusable, except for these
# which every home has or which the video can substitute around.
_ALWAYS_AVAILABLE = {"none", "bodyweight", "mat", "chair", "towel"}


@dataclass(frozen=True)
class Scored:
    item: object
    score: int
    reasons: tuple[str, ...] = ()


def _equipment_ok(profile: Profile, required: Sequence[str]) -> bool:
    owned = set(profile.equipment or []) | _ALWAYS_AVAILABLE
    if "gym" in owned:
        return True
    return all(item in owned for item in (required or []))


def _level_gap(profile_level: str, item_level: str) -> int:
    return _LEVEL_ORDER.get(item_level, 0) - _LEVEL_ORDER.get(profile_level, 0)


def score_video(profile: Profile, video: Video) -> int | None:
    """Score one video, or ``None`` when it is not a candidate at all."""
    if not video.published:
        return None
    if not _equipment_ok(profile, video.equipment):
        return None

    gap = _level_gap(profile.experience_level, video.difficulty)
    if gap > 1:
        # Two levels above where the user is: not appropriate, not a ranking
        # question.
        return None

    score = 50
    score += {0: 20, -1: 6, 1: 8}.get(gap, 0)

    # Session length: the closer to the time the user actually has, the better.
    if video.duration:
        delta = abs(video.duration - profile.session_minutes)
        score += max(0, 18 - delta)
        if video.duration > profile.session_minutes + 15:
            score -= 15

    for goal in profile.goals or []:
        score += _GOAL_CATEGORY_BONUS.get(goal, {}).get(video.category, 0)

    if not (video.equipment or []):
        score += 4  # zero-friction workouts win ties

    return score


def rank_videos(profile: Profile, videos: Iterable[Video], limit: int | None = None) -> list[Video]:
    scored: list[tuple[int, int, Video]] = []
    for video in videos:
        score = score_video(profile, video)
        if score is None:
            continue
        # id as a stable secondary key so ordering is deterministic
        scored.append((score, -video.id, video))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    ordered = [entry[2] for entry in scored]
    return ordered[:limit] if limit else ordered


def recipe_is_allowed(profile: Profile, recipe: Recipe) -> bool:
    """Hard exclusions. An allergy is never a ranking signal — it is a filter."""
    if not recipe.approved:
        return False
    allergies = {tag.lower() for tag in (profile.allergies or [])}
    if allergies & {tag.lower() for tag in (recipe.allergens or [])}:
        return False

    dietary = {tag.lower() for tag in (profile.dietary_tags or [])}
    recipe_tags = {tag.lower() for tag in (recipe.dietary_tags or [])}
    # A dietary preference the recipe does not declare is treated as a mismatch
    # for the strict ones only; "high_protein" is a preference, not a rule.
    strict = {"vegetarian", "vegan", "gluten_free", "dairy_free", "kosher"}
    for tag in dietary & strict:
        if tag not in recipe_tags:
            return False

    disliked = {item.strip().lower() for item in (profile.disliked_foods or []) if item.strip()}
    if disliked:
        haystack = " ".join(
            [recipe.name.lower(), recipe.description.lower()]
            + [str(ingredient.get("name", "")).lower() for ingredient in recipe.ingredients or []]
        )
        if any(item in haystack for item in disliked):
            return False
    return True


def score_recipe(profile: Profile, recipe: Recipe) -> int | None:
    if not recipe_is_allowed(profile, recipe):
        return None
    score = 50
    preferences = {tag.lower() for tag in (profile.dietary_tags or [])}
    score += 6 * len(preferences & {tag.lower() for tag in (recipe.dietary_tags or [])})
    if "high_protein" in preferences and "high_protein" in {
        tag.lower() for tag in (recipe.tags or [])
    }:
        score += 5
    if recipe.prep_minutes <= 15:
        score += 5
    elif recipe.prep_minutes > 45:
        score -= 5
    return score


def rank_recipes(profile: Profile, recipes: Iterable[Recipe], limit: int | None = None) -> list[Recipe]:
    scored: list[tuple[int, int, Recipe]] = []
    for recipe in recipes:
        score = score_recipe(profile, recipe)
        if score is None:
            continue
        scored.append((score, -recipe.id, recipe))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    ordered = [entry[2] for entry in scored]
    return ordered[:limit] if limit else ordered


def score_program(profile: Profile, program) -> int | None:
    if not program.published:
        return None
    gap = _level_gap(profile.experience_level, program.difficulty)
    if gap > 1:
        return None
    score = 50 + {0: 25, -1: 8, 1: 10}.get(gap, 0)
    goals = {goal.lower() for goal in (profile.goals or [])}
    score += 9 * len(goals & {tag.lower() for tag in (program.goal_tags or [])})
    if _equipment_ok(profile, program.equipment):
        score += 12
    else:
        score -= 25
    return score


def rank_programs(profile: Profile, programs: Iterable, limit: int | None = None) -> list:
    scored: list[tuple[int, int, object]] = []
    for program in programs:
        score = score_program(profile, program)
        if score is None:
            continue
        scored.append((score, -program.id, program))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    ordered = [entry[2] for entry in scored]
    return ordered[:limit] if limit else ordered


def assert_scope(path: GenderPath, items: Iterable) -> list:
    """Belt-and-braces: drop anything outside the caller's path.

    Repositories already scope their queries. This runs again on the way out of
    the engine, because a personalisation bug that leaks the other path's
    content is the one bug this product cannot ship (53).
    """
    return [item for item in items if can_view(path, getattr(item, "gender_path", None))]
