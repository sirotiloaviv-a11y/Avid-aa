"""Product analytics (35).

One vocabulary of event names, declared here, so the admin dashboard and the
call sites cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from ..db.repositories import insights

SIGNUP = "signup"
GENDER_SELECTED = "gender_selected"
ONBOARDING_STARTED = "onboarding_started"
ONBOARDING_COMPLETED = "onboarding_completed"
SUBSCRIPTION_STARTED = "subscription_started"
SUBSCRIPTION_COMPLETED = "subscription_completed"
SUBSCRIPTION_CANCELLED = "subscription_cancelled"
VIDEO_STARTED = "video_started"
VIDEO_COMPLETED = "video_completed"
PROGRAM_STARTED = "program_started"
PROGRAM_COMPLETED = "program_completed"
RECIPE_VIEWED = "recipe_viewed"
RECIPE_ADDED = "recipe_added"
MEAL_REPLACED = "meal_replaced"
AI_MESSAGE_SENT = "ai_message_sent"

FUNNEL = (
    SIGNUP,
    GENDER_SELECTED,
    ONBOARDING_STARTED,
    ONBOARDING_COMPLETED,
    SUBSCRIPTION_STARTED,
    SUBSCRIPTION_COMPLETED,
)

LABELS = {
    SIGNUP: "הרשמות",
    GENDER_SELECTED: "בחירת מסלול",
    ONBOARDING_STARTED: "התחלת שאלון",
    ONBOARDING_COMPLETED: "סיום שאלון",
    SUBSCRIPTION_STARTED: "התחלת מנוי",
    SUBSCRIPTION_COMPLETED: "מנוי שהושלם",
    SUBSCRIPTION_CANCELLED: "ביטול מנוי",
    VIDEO_STARTED: "צפיות שהתחילו",
    VIDEO_COMPLETED: "אימונים שהושלמו",
    PROGRAM_STARTED: "תוכניות שהתחילו",
    PROGRAM_COMPLETED: "תוכניות שהושלמו",
    RECIPE_VIEWED: "צפיות במתכון",
    RECIPE_ADDED: "מתכונים שנוספו",
    MEAL_REPLACED: "החלפות ארוחה",
    AI_MESSAGE_SENT: "הודעות ל‑AI",
}


def track(name: str, *, user_id: int | None = None, gender_path: str | None = None, **properties: Any) -> None:
    """Record an event. Never raises: analytics must not break a user flow."""
    try:
        insights.record_event(name, user_id=user_id, gender_path=gender_path, properties=properties)
    except Exception:  # pragma: no cover - defensive
        pass


def label(name: str) -> str:
    return LABELS.get(name, name)
