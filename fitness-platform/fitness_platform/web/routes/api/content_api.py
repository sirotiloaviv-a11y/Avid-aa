"""Read-only content endpoints, always scoped to the caller's path (43, 53)."""

from __future__ import annotations

from ....core.errors import NotFound, PaymentRequired
from ....core.request import Request
from ....core.response import Response, json_response
from ....core.router import Router
from ....db.repositories import content as content_repo
from ....domain.models import AuthContext
from ....services import analytics, program_service
from ....services.authorization import require_user


def _member(request: Request) -> AuthContext:
    ctx = require_user(request)
    if ctx.user.gender_path is None or not ctx.has_active_subscription:
        raise PaymentRequired()
    return ctx


def _video_json(video) -> dict:
    return {
        "id": video.id,
        "title": video.title,
        "duration": video.duration,
        "difficulty": video.difficulty,
        "category": video.category,
        "coach": video.coach_name,
        "completed": video.completed,
    }


def list_videos(request: Request) -> Response:
    ctx = _member(request)
    videos = content_repo.list_videos(
        ctx.user.gender_path,
        category=request.get("category"),
        difficulty=request.get("difficulty"),
        search=request.get("q"),
        user_id=ctx.user.id,
        limit=min(60, int(request.get("limit", "24") or 24)),
    )
    return json_response({"videos": [_video_json(video) for video in videos]})


def recommended(request: Request) -> Response:
    ctx = _member(request)
    return json_response(
        {"videos": [_video_json(video) for video in program_service.recommended_videos(ctx, limit=6)]}
    )


def get_video(request: Request) -> Response:
    ctx = _member(request)
    video = content_repo.get_video(request.int_param("video_id"), ctx.user.gender_path, user_id=ctx.user.id)
    if video is None:
        raise NotFound()
    return json_response(_video_json(video))


def complete_video(request: Request) -> Response:
    ctx = _member(request)
    video = content_repo.get_video(request.int_param("video_id"), ctx.user.gender_path)
    if video is None:
        raise NotFound()
    seconds = int(request.data().get("seconds_watched", 0) or 0)
    content_repo.mark_video_completed(ctx.user.id, video.id, seconds)
    analytics.track(
        analytics.VIDEO_COMPLETED,
        user_id=ctx.user.id,
        gender_path=ctx.user.gender_path.value,
        video_id=video.id,
    )
    return json_response({"video_id": video.id, "completed": True})


def register(router: Router) -> None:
    router.get("/api/videos", list_videos)
    router.get("/api/videos/recommended", recommended)
    router.get("/api/videos/<int:video_id>", get_video)
    router.post("/api/videos/<int:video_id>/complete", complete_video)
