"""Turning a profile into a concrete week of training (17, 18)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..db.repositories import content as content_repo
from ..domain.gender import GenderPath
from ..domain.models import AuthContext, Profile, Program, Video
from ..domain.rules_engine import assert_scope, rank_programs, rank_videos

HEBREW_DAYS = ("ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת")
# Single-letter day marks for the week strip; "ראשון" and "רביעי" share a first
# letter, so the conventional abbreviations are used rather than day[0].
HEBREW_DAY_MARKS = ("א", "ב", "ג", "ד", "ה", "ו", "ש")
DAY_KEYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


@dataclass
class ProgramPreview:
    program: Program | None
    sample_videos: list[Video]
    weekly_sessions: int
    session_minutes: int
    focus_labels: list[str]


def recommended_program(profile: Profile, path: GenderPath) -> Program | None:
    candidates = content_repo.list_programs(path)
    ranked = assert_scope(path, rank_programs(profile, candidates, limit=1))
    return ranked[0] if ranked else None


def build_preview(profile: Profile, path: GenderPath) -> ProgramPreview:
    """The "your plan is ready" screen (9). Read-only: nothing is charged or
    assigned until the member subscribes."""
    program = recommended_program(profile, path)
    videos = assert_scope(path, rank_videos(profile, content_repo.list_videos(path, limit=60), limit=3))
    focus = sorted({content_repo.CATEGORY_LABELS.get(video.category, video.category) for video in videos})
    return ProgramPreview(
        program=program,
        sample_videos=videos,
        weekly_sessions=profile.weekly_frequency,
        session_minutes=profile.session_minutes,
        focus_labels=focus,
    )


def assign_recommended_program(user_id: int, profile: Profile, path: GenderPath) -> Program | None:
    program = recommended_program(profile, path)
    if program:
        content_repo.assign_program(user_id, program.id)
    return program


def active_program(user_id: int, path: GenderPath) -> Program | None:
    program_id = content_repo.active_program_id(user_id)
    if not program_id:
        return None
    return content_repo.get_program(program_id, path)


def todays_workout(context: AuthContext) -> Video | None:
    """Pick today's session.

    Preference order: the next unfinished video in the assigned program, then
    the best-ranked video the member has not completed, then the best-ranked
    video overall (so the card is never empty for a returning member).
    """
    path = context.user.gender_path
    if path is None:
        return None
    completed = content_repo.completed_video_ids(context.user.id)

    program = active_program(context.user.id, path)
    if program:
        for day in program.days:
            for video in day.videos:
                if video.id not in completed:
                    return video

    candidates = content_repo.list_videos(path, user_id=context.user.id, limit=60)
    ranked = assert_scope(path, rank_videos(context.profile, candidates))
    for video in ranked:
        if video.id not in completed:
            return video
    return ranked[0] if ranked else None


def recommended_videos(context: AuthContext, limit: int = 4) -> list[Video]:
    path = context.user.gender_path
    if path is None:
        return []
    candidates = content_repo.list_videos(path, user_id=context.user.id, limit=60)
    return assert_scope(path, rank_videos(context.profile, candidates, limit=limit))


def week_overview(context: AuthContext) -> list[dict]:
    """The seven-day strip on the dashboard."""
    today = date.today()
    start = today - timedelta(days=(today.weekday() + 1) % 7)  # week starts Sunday
    completions = content_repo.completions_by_day(context.user.id, days=14)
    preferred = set(context.profile.preferred_days or [])
    days = []
    for index in range(7):
        current = start + timedelta(days=index)
        key = DAY_KEYS[index]
        iso = current.isoformat()
        if completions.get(iso):
            state = "done"
        elif current == today:
            state = "today"
        elif preferred and key not in preferred:
            state = "rest"
        else:
            state = "todo"
        days.append({"label": HEBREW_DAY_MARKS[index], "state": state, "date": iso})
    return days


def weekly_progress(context: AuthContext) -> dict:
    today = date.today()
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    completions = content_repo.completions_by_day(context.user.id, days=14)
    done = sum(
        count
        for day, count in completions.items()
        if day >= start.isoformat()
    )
    target = max(1, context.profile.weekly_frequency)
    return {
        "done": done,
        "target": target,
        "percent": min(100, round(100 * done / target)),
        "total_completed": content_repo.completed_count(context.user.id),
    }
