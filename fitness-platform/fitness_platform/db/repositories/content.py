"""Workout content: coaches, videos, programs.

Every read used by the product takes a ``GenderPath`` and scopes the SQL with
it. Admin reads go through the ``admin_*`` functions, which are only reachable
behind a role check (25, 46).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ...domain.gender import ContentScope, GenderPath, scope_sql
from ...domain.models import Coach, Program, ProgramDay, Video
from ..connection import execute, query, query_one, scalar, transaction
from ..json_fields import dumps

VIDEO_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("full_body", "גוף מלא"),
    ("upper_body", "פלג גוף עליון"),
    ("lower_body", "פלג גוף תחתון"),
    ("core", "ליבה ובטן"),
    ("warmup", "חימום"),
    ("stretch", "מתיחות"),
    ("short_workout", "אימון קצר"),
    ("technique", "טכניקה"),
    ("education", "לימוד והסבר"),
)
CATEGORY_LABELS = dict(VIDEO_CATEGORIES)

DIFFICULTIES: tuple[tuple[str, str], ...] = (
    ("beginner", "מתחילים"),
    ("intermediate", "בינוני"),
    ("advanced", "מתקדם"),
)
DIFFICULTY_LABELS = dict(DIFFICULTIES)


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ---------------------------------------------------------------- coaches ---
def create_coach(name: str, gender_path: ContentScope, photo_url: str = "", bio: str = "") -> int:
    return execute(
        "INSERT INTO coaches (name, gender_path, photo_url, bio) VALUES (?, ?, ?, ?)",
        (name, gender_path.value, photo_url, bio),
    )


def update_coach(coach_id: int, **fields: Any) -> None:
    allowed = {"name", "photo_url", "bio", "gender_path"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    execute(f"UPDATE coaches SET {assignments} WHERE id = ?", [*updates.values(), coach_id])


def get_coach(coach_id: int) -> Coach | None:
    return Coach.from_row(query_one("SELECT * FROM coaches WHERE id = ?", (coach_id,)))


def coach_for_path(path: GenderPath) -> Coach | None:
    return Coach.from_row(
        query_one("SELECT * FROM coaches WHERE gender_path = ? ORDER BY id LIMIT 1", (path.value,))
    )


def list_coaches() -> list[Coach]:
    return [Coach.from_row(row) for row in query("SELECT * FROM coaches ORDER BY id")]


# ----------------------------------------------------------------- videos ---
_VIDEO_SELECT = """
    SELECT v.*, c.name AS coach_name
      FROM videos v
      LEFT JOIN coaches c ON c.id = v.coach_id
"""


def list_videos(
    path: GenderPath,
    *,
    category: str = "",
    difficulty: str = "",
    search: str = "",
    max_duration: int = 0,
    user_id: int | None = None,
    limit: int = 60,
    offset: int = 0,
) -> list[Video]:
    scope_clause, params = scope_sql(path, "v.gender_path")
    clauses = [scope_clause, "v.published = 1"]
    if category:
        clauses.append("v.category = ?")
        params.append(category)
    if difficulty:
        clauses.append("v.difficulty = ?")
        params.append(difficulty)
    if max_duration:
        clauses.append("v.duration <= ?")
        params.append(max_duration)
    if search:
        clauses.append("(v.title LIKE ? OR v.description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    progress_select = ""
    if user_id:
        progress_select = ", (SELECT status FROM video_progress WHERE user_id = ? AND video_id = v.id) AS progress_status"
        params = [user_id, *params]

    sql = (
        _VIDEO_SELECT.replace("c.name AS coach_name", "c.name AS coach_name" + progress_select)
        + " WHERE "
        + " AND ".join(clauses)
        + " ORDER BY v.created_at DESC, v.id DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    return [Video.from_row(row) for row in query(sql, params)]


def get_video(video_id: int, path: GenderPath | None = None, user_id: int | None = None) -> Video | None:
    """Fetch one video.

    When ``path`` is given the scope is part of the WHERE clause, so a user
    asking for another path's video id gets ``None`` — a 404, never a 200 with
    the wrong content (2).
    """
    params: list[Any] = []
    progress_select = ""
    if user_id:
        progress_select = ", (SELECT status FROM video_progress WHERE user_id = ? AND video_id = v.id) AS progress_status"
        params.append(user_id)
    clauses = ["v.id = ?"]
    params.append(video_id)
    if path is not None:
        scope_clause, scope_params = scope_sql(path, "v.gender_path")
        clauses.extend([scope_clause, "v.published = 1"])
        params.extend(scope_params)
    sql = (
        _VIDEO_SELECT.replace("c.name AS coach_name", "c.name AS coach_name" + progress_select)
        + " WHERE "
        + " AND ".join(clauses)
        + " LIMIT 1"
    )
    return Video.from_row(query_one(sql, params))


def create_video(**fields: Any) -> int:
    return execute(
        """
        INSERT INTO videos (title, description, thumbnail_url, video_url, duration, difficulty,
                            category, gender_path, coach_id, equipment, tags, published,
                            created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields.get("title", ""),
            fields.get("description", ""),
            fields.get("thumbnail_url", ""),
            fields.get("video_url", ""),
            int(fields.get("duration") or 0),
            fields.get("difficulty", "beginner"),
            fields.get("category", "full_body"),
            fields.get("gender_path", "all"),
            fields.get("coach_id"),
            dumps(fields.get("equipment", [])),
            dumps(fields.get("tags", [])),
            1 if fields.get("published") else 0,
            _now(),
            _now(),
        ),
    )


_VIDEO_WRITABLE = {
    "title",
    "description",
    "thumbnail_url",
    "video_url",
    "duration",
    "difficulty",
    "category",
    "gender_path",
    "coach_id",
    "published",
}
_VIDEO_JSON = {"equipment", "tags"}


def update_video(video_id: int, **fields: Any) -> None:
    updates = {k: v for k, v in fields.items() if k in _VIDEO_WRITABLE or k in _VIDEO_JSON}
    if not updates:
        return
    assignments, params = [], []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        params.append(dumps(value) if key in _VIDEO_JSON else value)
    params.extend([_now(), video_id])
    execute(f"UPDATE videos SET {', '.join(assignments)}, updated_at = ? WHERE id = ?", params)


def delete_video(video_id: int) -> None:
    execute("DELETE FROM videos WHERE id = ?", (video_id,))


def admin_list_videos(
    *, gender_path: str = "", category: str = "", published: str = "", search: str = "",
    limit: int = 100, offset: int = 0,
) -> list[Video]:
    clauses, params = ["1 = 1"], []
    if gender_path:
        clauses.append("v.gender_path = ?")
        params.append(gender_path)
    if category:
        clauses.append("v.category = ?")
        params.append(category)
    if published in ("0", "1"):
        clauses.append("v.published = ?")
        params.append(int(published))
    if search:
        clauses.append("v.title LIKE ?")
        params.append(f"%{search}%")
    params.extend([limit, offset])
    sql = _VIDEO_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY v.id DESC LIMIT ? OFFSET ?"
    return [Video.from_row(row) for row in query(sql, params)]


# --------------------------------------------------------------- progress ---
def mark_video_started(user_id: int, video_id: int) -> None:
    execute(
        """
        INSERT INTO video_progress (user_id, video_id, status, created_at, updated_at)
        VALUES (?, ?, 'started', ?, ?)
        ON CONFLICT (user_id, video_id) DO UPDATE SET updated_at = excluded.updated_at
        """,
        (user_id, video_id, _now(), _now()),
    )


def mark_video_completed(user_id: int, video_id: int, seconds_watched: int = 0) -> None:
    execute(
        """
        INSERT INTO video_progress (user_id, video_id, status, seconds_watched, completed_at, created_at, updated_at)
        VALUES (?, ?, 'completed', ?, ?, ?, ?)
        ON CONFLICT (user_id, video_id) DO UPDATE SET
            status = 'completed',
            seconds_watched = MAX(video_progress.seconds_watched, excluded.seconds_watched),
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (user_id, video_id, seconds_watched, _now(), _now(), _now()),
    )


def completed_video_ids(user_id: int) -> set[int]:
    return {
        int(row["video_id"])
        for row in query(
            "SELECT video_id FROM video_progress WHERE user_id = ? AND status = 'completed'",
            (user_id,),
        )
    }


def recent_videos(user_id: int, path: GenderPath, limit: int = 4) -> list[Video]:
    scope_clause, scope_params = scope_sql(path, "v.gender_path")
    sql = f"""
        SELECT v.*, c.name AS coach_name, p.status AS progress_status
          FROM video_progress p
          JOIN videos v ON v.id = p.video_id
          LEFT JOIN coaches c ON c.id = v.coach_id
         WHERE p.user_id = ? AND {scope_clause}
         ORDER BY p.updated_at DESC
         LIMIT ?
    """
    return [Video.from_row(row) for row in query(sql, [user_id, *scope_params, limit])]


def completed_count(user_id: int, since: str | None = None) -> int:
    if since:
        return int(
            scalar(
                "SELECT COUNT(*) FROM video_progress WHERE user_id = ? AND status = 'completed' AND completed_at >= ?",
                (user_id, since),
            )
        )
    return int(
        scalar(
            "SELECT COUNT(*) FROM video_progress WHERE user_id = ? AND status = 'completed'",
            (user_id,),
        )
    )


def completions_by_day(user_id: int, days: int = 7) -> dict[str, int]:
    rows = query(
        """
        SELECT substr(completed_at, 1, 10) AS day, COUNT(*) AS total
          FROM video_progress
         WHERE user_id = ? AND status = 'completed' AND completed_at IS NOT NULL
         GROUP BY day ORDER BY day DESC LIMIT ?
        """,
        (user_id, days),
    )
    return {row["day"]: int(row["total"]) for row in rows}


def popular_videos(limit: int = 5) -> list[dict[str, Any]]:
    rows = query(
        """
        SELECT v.id, v.title, v.gender_path, v.category, COUNT(p.id) AS views
          FROM videos v LEFT JOIN video_progress p ON p.video_id = v.id
         GROUP BY v.id ORDER BY views DESC, v.id DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in rows]


# --------------------------------------------------------------- programs ---
def list_programs(path: GenderPath, *, published_only: bool = True) -> list[Program]:
    scope_clause, params = scope_sql(path)
    clauses = [scope_clause]
    if published_only:
        clauses.append("published = 1")
    return [
        Program.from_row(row)
        for row in query(
            f"SELECT * FROM workout_programs WHERE {' AND '.join(clauses)} ORDER BY id",
            params,
        )
    ]


def admin_list_programs(gender_path: str = "") -> list[Program]:
    if gender_path:
        rows = query("SELECT * FROM workout_programs WHERE gender_path = ? ORDER BY id DESC", (gender_path,))
    else:
        rows = query("SELECT * FROM workout_programs ORDER BY id DESC")
    return [Program.from_row(row) for row in rows]


def get_program(program_id: int, path: GenderPath | None = None, *, with_days: bool = True) -> Program | None:
    params: list[Any] = [program_id]
    clauses = ["id = ?"]
    if path is not None:
        scope_clause, scope_params = scope_sql(path)
        clauses.extend([scope_clause, "published = 1"])
        params.extend(scope_params)
    program = Program.from_row(
        query_one(f"SELECT * FROM workout_programs WHERE {' AND '.join(clauses)}", params)
    )
    if program and with_days:
        program.days = list_program_days(program.id)
    return program


def list_program_days(program_id: int) -> list[ProgramDay]:
    days: list[ProgramDay] = []
    for row in query(
        "SELECT * FROM workout_program_days WHERE program_id = ? ORDER BY day_number", (program_id,)
    ):
        day = ProgramDay(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            day_number=int(row["day_number"]),
            title=row["title"] or "",
            focus=row["focus"] or "",
            is_rest=bool(row["is_rest"]),
        )
        day.videos = [
            Video.from_row(video_row)
            for video_row in query(
                """
                SELECT v.*, c.name AS coach_name
                  FROM workout_program_day_videos dv
                  JOIN videos v ON v.id = dv.video_id
                  LEFT JOIN coaches c ON c.id = v.coach_id
                 WHERE dv.day_id = ?
                 ORDER BY dv.position, dv.id
                """,
                (day.id,),
            )
        ]
        days.append(day)
    return days


def create_program(**fields: Any) -> int:
    return execute(
        """
        INSERT INTO workout_programs (name, description, gender_path, duration_weeks, difficulty,
                                      goal_tags, equipment, cover_url, published, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields.get("name", ""),
            fields.get("description", ""),
            fields.get("gender_path", "all"),
            int(fields.get("duration_weeks") or 4),
            fields.get("difficulty", "beginner"),
            dumps(fields.get("goal_tags", [])),
            dumps(fields.get("equipment", [])),
            fields.get("cover_url", ""),
            1 if fields.get("published") else 0,
            _now(),
            _now(),
        ),
    )


def update_program(program_id: int, **fields: Any) -> None:
    writable = {"name", "description", "gender_path", "duration_weeks", "difficulty", "cover_url", "published"}
    json_fields = {"goal_tags", "equipment"}
    updates = {k: v for k, v in fields.items() if k in writable or k in json_fields}
    if not updates:
        return
    assignments, params = [], []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        params.append(dumps(value) if key in json_fields else value)
    params.extend([_now(), program_id])
    execute(
        f"UPDATE workout_programs SET {', '.join(assignments)}, updated_at = ? WHERE id = ?", params
    )


def delete_program(program_id: int) -> None:
    execute("DELETE FROM workout_programs WHERE id = ?", (program_id,))


def add_program_day(program_id: int, day_number: int, title: str, focus: str = "", is_rest: bool = False) -> int:
    return execute(
        """
        INSERT INTO workout_program_days (program_id, day_number, title, focus, is_rest)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (program_id, day_number) DO UPDATE SET
            title = excluded.title, focus = excluded.focus, is_rest = excluded.is_rest
        """,
        (program_id, day_number, title, focus, 1 if is_rest else 0),
    )


def set_day_videos(day_id: int, video_ids: Iterable[int]) -> None:
    with transaction() as connection:
        connection.execute("DELETE FROM workout_program_day_videos WHERE day_id = ?", (day_id,))
        connection.executemany(
            "INSERT INTO workout_program_day_videos (day_id, video_id, position) VALUES (?, ?, ?)",
            [(day_id, video_id, index) for index, video_id in enumerate(video_ids)],
        )


# ---------------------------------------------------------- user programs ---
def assign_program(user_id: int, program_id: int) -> None:
    execute(
        """
        INSERT INTO user_programs (user_id, program_id, status, started_at)
        VALUES (?, ?, 'active', ?)
        ON CONFLICT (user_id, program_id) DO UPDATE SET status = 'active'
        """,
        (user_id, program_id, _now()),
    )


def active_program_id(user_id: int) -> int | None:
    row = query_one(
        "SELECT program_id FROM user_programs WHERE user_id = ? AND status = 'active' ORDER BY started_at DESC LIMIT 1",
        (user_id,),
    )
    return int(row["program_id"]) if row else None


def program_ids_for_user(user_id: int) -> list[int]:
    return [int(row["program_id"]) for row in query("SELECT program_id FROM user_programs WHERE user_id = ?", (user_id,))]
