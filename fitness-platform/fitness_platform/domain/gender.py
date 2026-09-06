"""The women/men split.

This module is the single place that answers "may this user see this thing?".
Routes, the API layer, the AI coach and every repository query funnel through
it, so the rule is enforced once and can be tested once (2, 14, 53).

Two vocabularies exist and must not be confused:

* ``GenderPath``  — what a *user* is on: female or male. Never "all".
* ``ContentScope``— what a *content row* is tagged with: female, male, or all.

A user on the female path may read content scoped ``female`` or ``all``, and
nothing else. There is no code path that widens this for a normal user; admins
do not read content through these helpers at all, they use the admin
repositories, which are behind a separate role check.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class GenderPath(str, Enum):
    FEMALE = "female"
    MALE = "male"

    @property
    def url_segment(self) -> str:
        return "women" if self is GenderPath.FEMALE else "men"

    @property
    def theme(self) -> str:
        return "theme-women" if self is GenderPath.FEMALE else "theme-men"

    @property
    def label(self) -> str:
        return "נשים" if self is GenderPath.FEMALE else "גברים"

    @classmethod
    def parse(cls, raw: object) -> "GenderPath | None":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            return None
        value = raw.strip().lower()
        aliases = {
            "female": cls.FEMALE,
            "woman": cls.FEMALE,
            "women": cls.FEMALE,
            "f": cls.FEMALE,
            "male": cls.MALE,
            "man": cls.MALE,
            "men": cls.MALE,
            "m": cls.MALE,
        }
        return aliases.get(value)

    @classmethod
    def from_url_segment(cls, segment: str) -> "GenderPath | None":
        return {"women": cls.FEMALE, "men": cls.MALE}.get(segment.strip().lower())


class ContentScope(str, Enum):
    FEMALE = "female"
    MALE = "male"
    ALL = "all"

    @classmethod
    def parse(cls, raw: object) -> "ContentScope | None":
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, GenderPath):
            return cls(raw.value)
        if not isinstance(raw, str):
            return None
        value = raw.strip().lower()
        try:
            return cls(value)
        except ValueError:
            path = GenderPath.parse(value)
            return cls(path.value) if path else None


def visible_scopes(path: GenderPath) -> tuple[str, str]:
    """The content scopes a user on ``path`` is allowed to read."""
    return (path.value, ContentScope.ALL.value)


def can_view(path: GenderPath | None, scope: object) -> bool:
    """Whether a user on ``path`` may read a row tagged ``scope``."""
    if path is None:
        return False
    parsed = ContentScope.parse(scope)
    if parsed is None:
        return False
    return parsed is ContentScope.ALL or parsed.value == path.value


def filter_visible(path: GenderPath | None, rows: Iterable[dict]) -> list[dict]:
    """Defence in depth: drop anything a hand-written query let through."""
    return [row for row in rows if can_view(path, row.get("gender_path"))]


def scope_sql(path: GenderPath, column: str = "gender_path") -> tuple[str, list[str]]:
    """A parameterised ``WHERE`` fragment restricting a query to ``path``."""
    return f"{column} IN (?, ?)", list(visible_scopes(path))


def other_path(path: GenderPath) -> GenderPath:
    return GenderPath.MALE if path is GenderPath.FEMALE else GenderPath.FEMALE
