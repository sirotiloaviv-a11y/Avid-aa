"""The member-facing assistant (21).

Two rules shape this module:

1. The coach can only see what its member can see. The context blocks are built
   from repositories called with the member's own ``GenderPath``, so a female
   member's assistant is physically unable to cite a male workout — there is no
   filter to forget, because the other path's rows are never fetched.
2. The coach is not a clinician and not an admin. Questions that read as medical
   get a fixed reply, and the provider is never handed a tool, a database handle
   or a permission.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import get_settings
from ...core.errors import RateLimited
from ...db.repositories import ai as ai_repo, content as content_repo, food as food_repo
from ...domain.gender import GenderPath
from ...domain.models import AuthContext
from ...domain.rules_engine import assert_scope, rank_recipes, rank_videos
from .. import analytics
from .factory import get_provider
from .provider import AIMessage, AIRequest
from .safety import check_question, sanitize_answer

MAX_HISTORY = 8

SYSTEM_PROMPT = """אתה עוזר דיגיטלי של פלטפורמת כושר ותזונה, כותב בעברית, בגוף שני, בקצרה ובחום.

כללים מחייבים:
- ענה רק על סמך רשימת התוכן המאושר שמצורפת להודעה. אל תמציא אימונים, מתכונים או שמות מאמנים.
- אם אין בתוכן פריט מתאים, אמור זאת בפשטות והצע לפנות לתמיכה.
- אינך רופא, דיאטן או פיזיותרפיסט. אל תיתן ייעוץ רפואי, אבחנה, מינון או תוכנית קלורית אישית.
- אינך מבצע פעולות במערכת: אינך מבטל מנויים, מוחק תוכן או משנה הרשאות. הפנה להגדרות החשבון.
- שמור על תשובה קצרה: עד חמישה משפטים או רשימה קצרה."""

SUGGESTIONS_FEMALE = (
    "איזה אימון מתאים לי היום?",
    "אפשר להחליף את ארוחת הצהריים?",
    "יש אימון קצר של 15 דקות?",
    "איך מוסיפים מתכון לרשימת הקניות?",
)
SUGGESTIONS_MALE = (
    "איזה אימון מתאים לי היום?",
    "מה מומלץ ליום רגליים?",
    "יש אימון קצר בלי ציוד?",
    "איך בונים שבוע אימונים?",
)


@dataclass
class CoachReply:
    text: str
    status: str
    provider: str


def suggestions(path: GenderPath) -> tuple[str, ...]:
    return SUGGESTIONS_FEMALE if path is GenderPath.FEMALE else SUGGESTIONS_MALE


def build_context_blocks(context: AuthContext, question: str) -> list[str]:
    """Assemble the approved content the assistant may cite (18, 21)."""
    path = context.user.gender_path
    if path is None:
        return []
    profile = context.profile
    blocks: list[str] = []

    videos = assert_scope(
        path, rank_videos(profile, content_repo.list_videos(path, limit=40), limit=6)
    )
    if videos:
        lines = "\n".join(
            f"- {video.title} · {video.duration} דקות · "
            f"{content_repo.CATEGORY_LABELS.get(video.category, video.category)} · "
            f"{content_repo.DIFFICULTY_LABELS.get(video.difficulty, video.difficulty)}"
            for video in videos
        )
        blocks.append("אימונים מאושרים שמתאימים למשתמש/ת:\n" + lines)

    recipes = assert_scope(path, rank_recipes(profile, food_repo.list_recipes(path, limit=40), limit=6))
    if recipes:
        lines = "\n".join(
            f"- {recipe.name} · {food_repo.MEAL_TYPE_LABELS.get(recipe.meal_type, recipe.meal_type)} · "
            f"{recipe.prep_minutes} דקות הכנה"
            for recipe in recipes
        )
        blocks.append("מתכונים מאושרים שמתאימים למשתמש/ת:\n" + lines)

    blocks.append(
        "פרופיל המשתמש/ת: "
        f"רמה {profile.experience_level}, {profile.weekly_frequency} אימונים בשבוע, "
        f"{profile.session_minutes} דקות לאימון. "
        f"ציוד: {', '.join(profile.equipment) or 'ללא'}. "
        f"רגישויות: {', '.join(profile.allergies) or 'אין'}."
    )
    return blocks


def history(context: AuthContext) -> list[dict]:
    path = context.user.gender_path
    if path is None:
        return []
    conversation_id = ai_repo.get_or_create_conversation(context.user.id, path)
    return ai_repo.list_messages(conversation_id, limit=MAX_HISTORY * 2)


def ask(context: AuthContext, question: str) -> CoachReply:
    path = context.user.gender_path
    if path is None:
        return CoachReply("צריך לבחור מסלול לפני שימוש במאמן.", "blocked", "none")

    settings = get_settings()
    if ai_repo.messages_today(context.user.id) >= settings.ai_daily_message_limit:
        raise RateLimited("הגעת למכסת ההודעות היומית של המאמן. נתראה מחר!")

    conversation_id = ai_repo.get_or_create_conversation(context.user.id, path)
    allowed, replacement = check_question(question)
    ai_repo.add_message(conversation_id, "user", question.strip()[:800])
    analytics.track(analytics.AI_MESSAGE_SENT, user_id=context.user.id, gender_path=path.value)

    if not allowed:
        ai_repo.add_message(conversation_id, "assistant", replacement, provider="guard", status="blocked")
        return CoachReply(replacement, "blocked", "guard")

    prior = [
        AIMessage(role=message["role"], content=message["content"])
        for message in ai_repo.list_messages(conversation_id, limit=MAX_HISTORY)
        if message["role"] in ("user", "assistant")
    ][-MAX_HISTORY:]

    provider = get_provider()
    response = provider.complete(
        AIRequest(
            system=SYSTEM_PROMPT,
            messages=prior or [AIMessage("user", question)],
            context_blocks=build_context_blocks(context, question),
            metadata={"gender_path": path.value, "user_id": context.user.id},
        )
    )

    if response.status != "ok":
        fallback = "לא הצלחתי להשיג תשובה כרגע. אפשר לנסות שוב בעוד רגע."
        ai_repo.add_message(
            conversation_id, "assistant", fallback, provider=response.provider,
            latency_ms=response.latency_ms, status="error",
        )
        return CoachReply(fallback, "error", response.provider)

    text = sanitize_answer(response.text)
    ai_repo.add_message(
        conversation_id,
        "assistant",
        text,
        provider=response.provider,
        tokens=response.tokens,
        latency_ms=response.latency_ms,
    )
    return CoachReply(text, "ok", response.provider)
