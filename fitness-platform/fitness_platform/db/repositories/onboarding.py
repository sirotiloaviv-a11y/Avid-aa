"""Questionnaire answers and step progress (7, 11).

Progress is stored server-side so a user who leaves before paying resumes
exactly where they stopped, on any device.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..connection import execute, query, query_one, transaction


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def save_answers(user_id: int, step_key: str, answers: dict[str, Any]) -> None:
    with transaction() as connection:
        for question_key, value in answers.items():
            connection.execute(
                """
                INSERT INTO onboarding_answers (user_id, step_key, question_key, answer, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, question_key) DO UPDATE SET
                    answer = excluded.answer,
                    step_key = excluded.step_key,
                    updated_at = excluded.updated_at
                """,
                (user_id, step_key, question_key, json.dumps(value, ensure_ascii=False), _now(), _now()),
            )


def get_answers(user_id: int) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for row in query("SELECT question_key, answer FROM onboarding_answers WHERE user_id = ?", (user_id,)):
        try:
            answers[row["question_key"]] = json.loads(row["answer"])
        except (json.JSONDecodeError, TypeError):
            answers[row["question_key"]] = row["answer"]
    return answers


def set_progress(user_id: int, current_step: int, total_steps: int) -> None:
    execute(
        """
        INSERT INTO onboarding_progress (user_id, current_step, total_steps, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (user_id) DO UPDATE SET
            current_step = excluded.current_step,
            total_steps = excluded.total_steps,
            updated_at = excluded.updated_at
        """,
        (user_id, current_step, total_steps, _now()),
    )


def get_progress(user_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM onboarding_progress WHERE user_id = ?", (user_id,))
    if not row:
        return {"current_step": 0, "total_steps": 0, "completed_at": None}
    return dict(row)


def mark_completed(user_id: int) -> None:
    execute(
        """
        INSERT INTO onboarding_progress (user_id, current_step, total_steps, completed_at, updated_at)
        VALUES (?, 0, 0, ?, ?)
        ON CONFLICT (user_id) DO UPDATE SET completed_at = excluded.completed_at, updated_at = excluded.updated_at
        """,
        (user_id, _now(), _now()),
    )
