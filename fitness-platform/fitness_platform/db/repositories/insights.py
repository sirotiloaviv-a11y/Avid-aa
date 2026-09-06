"""Analytics events, audit logs and body-progress entries (35, 34)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..connection import execute, query, query_one, scalar


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# -------------------------------------------------------------- analytics ---
def record_event(
    name: str, *, user_id: int | None = None, gender_path: str | None = None, properties: dict | None = None
) -> None:
    execute(
        "INSERT INTO analytics_events (user_id, name, gender_path, properties, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, name, gender_path, json.dumps(properties or {}, ensure_ascii=False), _now()),
    )


def event_counts(days: int = 30) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    return [
        dict(row)
        for row in query(
            """
            SELECT name, COUNT(*) AS total,
                   SUM(CASE WHEN gender_path = 'female' THEN 1 ELSE 0 END) AS female,
                   SUM(CASE WHEN gender_path = 'male'   THEN 1 ELSE 0 END) AS male
              FROM analytics_events WHERE created_at >= ?
             GROUP BY name ORDER BY total DESC
            """,
            (cutoff,),
        )
    ]


def events_by_day(name: str, days: int = 14) -> dict[str, int]:
    rows = query(
        """
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS total
          FROM analytics_events WHERE name = ?
         GROUP BY day ORDER BY day DESC LIMIT ?
        """,
        (name, days),
    )
    return {row["day"]: int(row["total"]) for row in rows}


def funnel(names: list[str], days: int = 30) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    result = []
    for name in names:
        total = int(
            scalar(
                "SELECT COUNT(DISTINCT COALESCE(user_id, id)) FROM analytics_events WHERE name = ? AND created_at >= ?",
                (name, cutoff),
            )
        )
        result.append({"name": name, "total": total})
    return result


# ------------------------------------------------------------------ audit ---
def record_audit(
    actor_id: int | None,
    action: str,
    *,
    entity_type: str = "",
    entity_id: str = "",
    details: dict | None = None,
    ip_address: str = "",
) -> None:
    execute(
        """
        INSERT INTO admin_audit_logs (actor_id, action, entity_type, entity_id, details, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (actor_id, action, entity_type, str(entity_id), json.dumps(details or {}, ensure_ascii=False), ip_address, _now()),
    )


def list_audit(limit: int = 50) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query(
            """
            SELECT a.*, u.name AS actor_name, u.email AS actor_email
              FROM admin_audit_logs a LEFT JOIN users u ON u.id = a.actor_id
             ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        )
    ]


# --------------------------------------------------------- body progress ----
def upsert_progress_entry(user_id: int, entry_date: str, weight_kg: float | None, note: str = "") -> None:
    execute(
        """
        INSERT INTO progress_entries (user_id, entry_date, weight_kg, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (user_id, entry_date) DO UPDATE SET
            weight_kg = excluded.weight_kg, note = excluded.note
        """,
        (user_id, entry_date, weight_kg, note[:300], _now()),
    )


def list_progress_entries(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM progress_entries WHERE user_id = ? ORDER BY entry_date DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(row) for row in reversed(rows)]


def latest_progress_entry(user_id: int) -> dict[str, Any] | None:
    row = query_one(
        "SELECT * FROM progress_entries WHERE user_id = ? ORDER BY entry_date DESC LIMIT 1", (user_id,)
    )
    return dict(row) if row else None
