"""Users, profiles and sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ...domain.gender import GenderPath
from ...domain.models import Profile, User
from ...domain.roles import Role
from ..connection import execute, query, query_one, scalar, transaction
from ..json_fields import dumps

_PROFILE_JSON_FIELDS = {
    "equipment",
    "goals",
    "dietary_tags",
    "allergies",
    "disliked_foods",
    "preferred_days",
}
_PROFILE_COLUMNS = {
    "display_name",
    "avatar_url",
    "birth_year",
    "height_cm",
    "weight_kg",
    "experience_level",
    "weekly_frequency",
    "session_minutes",
    "meals_per_day",
} | _PROFILE_JSON_FIELDS


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ------------------------------------------------------------------ users ---
def create_user(
    email: str,
    password_hash: str,
    *,
    name: str = "",
    gender_path: GenderPath | None = None,
    role: Role = Role.USER,
) -> int:
    user_id = execute(
        """
        INSERT INTO users (email, name, password_hash, role, gender_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email.strip().lower(),
            name.strip(),
            password_hash,
            role.value,
            gender_path.value if gender_path else None,
            _now(),
            _now(),
        ),
    )
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, display_name) VALUES (?, ?)",
        (user_id, name.strip()),
    )
    return user_id


def get_user(user_id: int) -> User | None:
    return User.from_row(query_one("SELECT * FROM users WHERE id = ? AND status != 'deleted'", (user_id,)))


def get_user_by_email(email: str) -> User | None:
    return User.from_row(
        query_one("SELECT * FROM users WHERE email = ? AND status != 'deleted'", (email.strip().lower(),))
    )


def get_password_hash(user_id: int) -> str:
    row = query_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    return row["password_hash"] if row else ""


def email_exists(email: str) -> bool:
    return bool(scalar("SELECT COUNT(*) FROM users WHERE email = ?", (email.strip().lower(),)))


def set_gender_path(user_id: int, path: GenderPath) -> None:
    """Set the user's path.

    Deliberately one-way: once a path is set it is not changed by a request
    parameter. Moving a user between paths is a support action performed by an
    admin, and it is audited (53).
    """
    execute(
        "UPDATE users SET gender_path = ?, updated_at = ? WHERE id = ? AND gender_path IS NULL",
        (path.value, _now(), user_id),
    )


def admin_set_gender_path(user_id: int, path: GenderPath) -> None:
    execute(
        "UPDATE users SET gender_path = ?, updated_at = ? WHERE id = ?",
        (path.value, _now(), user_id),
    )


def mark_onboarding_complete(user_id: int) -> None:
    execute(
        "UPDATE users SET onboarding_completed = 1, updated_at = ? WHERE id = ?",
        (_now(), user_id),
    )


def touch_last_active(user_id: int) -> None:
    execute("UPDATE users SET last_active_at = ? WHERE id = ?", (_now(), user_id))


def update_password(user_id: int, password_hash: str) -> None:
    execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (password_hash, _now(), user_id),
    )


def update_profile_name(user_id: int, name: str) -> None:
    execute("UPDATE users SET name = ?, updated_at = ? WHERE id = ?", (name.strip(), _now(), user_id))


def set_role(user_id: int, role: Role) -> None:
    execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role.value, _now(), user_id))


def set_status(user_id: int, status: str) -> None:
    execute("UPDATE users SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), user_id))


def delete_account(user_id: int) -> None:
    """Erase personal data, keep aggregate rows anonymous (47).

    The user row is tombstoned rather than dropped so foreign keys in payment
    history stay valid for accounting; every identifying column is cleared.
    """
    with transaction() as connection:
        connection.execute(
            """
            UPDATE users
               SET email = 'deleted+' || id || '@invalid',
                   name = '',
                   password_hash = '',
                   status = 'deleted',
                   gender_path = NULL,
                   updated_at = ?
             WHERE id = ?
            """,
            (_now(), user_id),
        )
        connection.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM onboarding_answers WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM ai_conversations WHERE user_id = ?", (user_id,))
        connection.execute("UPDATE analytics_events SET user_id = NULL WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------- profiles ---
def get_profile(user_id: int) -> Profile:
    row = query_one("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    if row is None:
        execute("INSERT OR IGNORE INTO profiles (user_id) VALUES (?)", (user_id,))
        row = query_one("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    return Profile.from_row(row) or Profile.empty(user_id)


def update_profile(user_id: int, updates: dict[str, Any]) -> None:
    fields = {key: value for key, value in updates.items() if key in _PROFILE_COLUMNS}
    if not fields:
        return
    assignments = []
    params: list[Any] = []
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        params.append(dumps(value) if key in _PROFILE_JSON_FIELDS else value)
    params.extend([_now(), user_id])
    execute(
        f"UPDATE profiles SET {', '.join(assignments)}, updated_at = ? WHERE user_id = ?",
        params,
    )


# --------------------------------------------------------------- sessions ---
def create_session(
    session_id: str,
    user_id: int,
    csrf_token: str,
    ttl_seconds: int,
    *,
    user_agent: str = "",
    ip_address: str = "",
) -> None:
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl_seconds)
    execute(
        """
        INSERT INTO sessions (id, user_id, csrf_token, user_agent, ip_address, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            user_id,
            csrf_token,
            user_agent[:250],
            ip_address[:60],
            expires.isoformat(timespec="seconds"),
            _now(),
        ),
    )


def get_session(session_id: str) -> dict[str, Any] | None:
    row = query_one(
        "SELECT * FROM sessions WHERE id = ? AND expires_at > ?",
        (session_id, _now()),
    )
    return dict(row) if row else None


def delete_session(session_id: str) -> None:
    execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_user_sessions(user_id: int) -> None:
    execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def purge_expired_sessions() -> None:
    execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))


# ------------------------------------------------------------ admin views ---
def count_users(**filters: Any) -> int:
    where, params = _user_filters(filters)
    return int(scalar(f"SELECT COUNT(*) FROM users WHERE {where}", params))


def _user_filters(filters: dict[str, Any], prefix: str = "") -> tuple[str, list[Any]]:
    """Build the WHERE fragment. ``prefix`` qualifies the columns when the query
    joins another table that has columns of the same name (``status``)."""
    column = (prefix + ".") if prefix else ""
    clauses = [f"{column}status != 'deleted'"]
    params: list[Any] = []
    if filters.get("gender_path"):
        clauses.append(f"{column}gender_path = ?")
        params.append(filters["gender_path"])
    if filters.get("role"):
        clauses.append(f"{column}role = ?")
        params.append(filters["role"])
    if filters.get("search"):
        clauses.append(f"({column}email LIKE ? OR {column}name LIKE ?)")
        term = f"%{filters['search']}%"
        params.extend([term, term])
    return " AND ".join(clauses), params


def list_users(
    *,
    gender_path: str = "",
    role: str = "",
    search: str = "",
    subscription_status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _user_filters(
        {"gender_path": gender_path, "role": role, "search": search}, prefix="u"
    )
    sql = f"""
        SELECT u.*,
               s.status     AS subscription_status,
               s.plan_code  AS subscription_plan
          FROM users u
          LEFT JOIN subscriptions s
                 ON s.id = (SELECT id FROM subscriptions
                             WHERE user_id = u.id ORDER BY id DESC LIMIT 1)
         WHERE {where}
    """
    if subscription_status:
        sql += " AND COALESCE(s.status, 'none') = ?"
        params.append(subscription_status)
    sql += " ORDER BY u.created_at DESC, u.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [dict(row) for row in query(sql, params)]


def gender_distribution() -> dict[str, int]:
    rows = query(
        """
        SELECT COALESCE(gender_path, 'unset') AS path, COUNT(*) AS total
          FROM users WHERE status != 'deleted' AND role = 'user'
         GROUP BY COALESCE(gender_path, 'unset')
        """
    )
    return {row["path"]: int(row["total"]) for row in rows}


def signups_by_day(days: int = 14) -> list[dict[str, Any]]:
    rows = query(
        """
        SELECT substr(created_at, 1, 10) AS day,
               SUM(CASE WHEN gender_path = 'female' THEN 1 ELSE 0 END) AS female,
               SUM(CASE WHEN gender_path = 'male'   THEN 1 ELSE 0 END) AS male,
               COUNT(*) AS total
          FROM users
         WHERE status != 'deleted' AND role = 'user'
         GROUP BY day
         ORDER BY day DESC
         LIMIT ?
        """,
        (days,),
    )
    return [dict(row) for row in reversed(rows)]


def active_user_count(days: int = 7) -> int:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    return int(
        scalar(
            "SELECT COUNT(*) FROM users WHERE status != 'deleted' AND last_active_at >= ?",
            (cutoff,),
        )
    )
