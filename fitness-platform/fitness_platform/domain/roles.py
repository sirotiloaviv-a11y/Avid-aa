"""Roles and what each one may do (3, 46)."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    USER = "user"
    ADMIN = "admin"
    # Reserved for the next milestone; parsed and stored today so the column
    # never needs a migration, but granted no extra permissions yet.
    CONTENT_MANAGER = "content_manager"
    NUTRITION_SPECIALIST = "nutrition_specialist"

    @classmethod
    def parse(cls, raw: object) -> "Role":
        if isinstance(raw, cls):
            return raw
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.USER

    @property
    def label(self) -> str:
        return {
            Role.USER: "משתמש",
            Role.ADMIN: "אדמין",
            Role.CONTENT_MANAGER: "מנהל תוכן",
            Role.NUTRITION_SPECIALIST: "מומחה תזונה",
        }[self]


class Permission(str, Enum):
    MANAGE_USERS = "manage_users"
    MANAGE_CONTENT = "manage_content"
    MANAGE_SUBSCRIPTIONS = "manage_subscriptions"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_AI = "manage_ai"
    USE_APP = "use_app"


_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset({Permission.USE_APP}),
    Role.ADMIN: frozenset(Permission),
    Role.CONTENT_MANAGER: frozenset({Permission.USE_APP, Permission.MANAGE_CONTENT}),
    Role.NUTRITION_SPECIALIST: frozenset({Permission.USE_APP, Permission.MANAGE_CONTENT}),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return _ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in permissions_for(role)
