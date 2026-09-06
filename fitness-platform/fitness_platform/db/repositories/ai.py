"""AI conversation storage and usage stats (21, 28)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ...domain.gender import GenderPath
from ..connection import execute, query, query_one, scalar


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def get_or_create_conversation(user_id: int, path: GenderPath) -> int:
    row = query_one(
        "SELECT id FROM ai_conversations WHERE user_id = ? AND gender_path = ? ORDER BY id DESC LIMIT 1",
        (user_id, path.value),
    )
    if row:
        return int(row["id"])
    return execute(
        "INSERT INTO ai_conversations (user_id, gender_path, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, path.value, _now(), _now()),
    )


def conversation_owner(conversation_id: int) -> tuple[int, str] | None:
    row = query_one("SELECT user_id, gender_path FROM ai_conversations WHERE id = ?", (conversation_id,))
    return (int(row["user_id"]), row["gender_path"]) if row else None


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    *,
    provider: str = "",
    tokens: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
) -> int:
    message_id = execute(
        """
        INSERT INTO ai_messages (conversation_id, role, content, provider, tokens, latency_ms, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (conversation_id, role, content, provider, tokens, latency_ms, status, _now()),
    )
    execute("UPDATE ai_conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))
    return message_id


def list_messages(conversation_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM ai_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [dict(row) for row in reversed(rows)]


def messages_today(user_id: int) -> int:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).isoformat(
        timespec="seconds"
    )
    return int(
        scalar(
            """
            SELECT COUNT(*) FROM ai_messages m
              JOIN ai_conversations c ON c.id = m.conversation_id
             WHERE c.user_id = ? AND m.role = 'user' AND m.created_at >= ?
            """,
            (user_id, cutoff),
        )
    )


# ------------------------------------------------------------ admin stats ---
def usage_stats(days: int = 30) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    return {
        "requests": int(
            scalar("SELECT COUNT(*) FROM ai_messages WHERE role = 'user' AND created_at >= ?", (cutoff,))
        ),
        "responses": int(
            scalar("SELECT COUNT(*) FROM ai_messages WHERE role = 'assistant' AND created_at >= ?", (cutoff,))
        ),
        "errors": int(
            scalar("SELECT COUNT(*) FROM ai_messages WHERE status = 'error' AND created_at >= ?", (cutoff,))
        ),
        "blocked": int(
            scalar("SELECT COUNT(*) FROM ai_messages WHERE status = 'blocked' AND created_at >= ?", (cutoff,))
        ),
        "avg_latency_ms": int(
            scalar(
                "SELECT COALESCE(AVG(latency_ms), 0) FROM ai_messages WHERE role = 'assistant' AND created_at >= ?",
                (cutoff,),
            )
        ),
        "conversations": int(scalar("SELECT COUNT(*) FROM ai_conversations")),
    }


def common_questions(limit: int = 8) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query(
            """
            SELECT content, COUNT(*) AS total, MAX(created_at) AS last_seen
              FROM ai_messages WHERE role = 'user'
             GROUP BY lower(trim(content)) ORDER BY total DESC, last_seen DESC LIMIT ?
            """,
            (limit,),
        )
    ]


def recent_failures(limit: int = 10) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query(
            """
            SELECT m.*, c.gender_path FROM ai_messages m
              JOIN ai_conversations c ON c.id = m.conversation_id
             WHERE m.status IN ('error', 'blocked')
             ORDER BY m.id DESC LIMIT ?
            """,
            (limit,),
        )
    ]
