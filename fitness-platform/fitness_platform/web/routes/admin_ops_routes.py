"""Admin operations: AI control centre, analytics, system settings (28, 35, 40)."""

from __future__ import annotations

from ...config import get_settings
from ...core.errors import NotFound
from ...core.request import Request
from ...core.response import Response, html
from ...core.router import Router
from ...db.repositories import ai as ai_repo, content as content_repo, insights
from ...services import analytics
from ...services.ai.factory import get_provider as get_ai_provider
from ...services.authorization import require_admin
from ...services.payments.factory import get_provider as get_payment_provider
from ..support import flash_redirect
from ..ui.components import (
    badge,
    button,
    card,
    card_header,
    csrf_input,
    empty_state,
    stat_card,
    table,
    text_input,
    textarea,
)
from ..ui.icons import icon
from ..ui.layouts import admin_layout
from ..ui.primitives import esc, join
from .admin_content_routes import scope_badge


def mode_flag() -> str:
    settings = get_settings()
    if settings.mode == "production":
        return ""
    return (
        f'<span class="mode-flag">{icon("info", size=14)} מצב {esc(settings.mode)} — '
        f"AI: {esc(settings.ai_provider)}, תשלומים: {esc(settings.payment_provider)}</span>"
    )


def _row(label: str, value: str, trailing: str = "") -> str:
    return (
        '<div class="list-row"><div class="list-row-main">'
        f'<p class="list-row-meta">{esc(label)}</p>'
        f'<p class="list-row-title">{value}</p></div>{trailing}</div>'
    )


# ------------------------------------------------------------------- AI -----
def ai_page(request: Request) -> Response:
    ctx = require_admin(request)
    settings = get_settings()
    stats = ai_repo.usage_stats(30)
    provider = get_ai_provider()

    question_rows = [
        [esc(row["content"][:110]), str(row["total"]), f'<span class="ltr-num">{esc(str(row["last_seen"])[:16])}</span>']
        for row in ai_repo.common_questions(8)
    ]
    failure_rows = [
        [
            badge(row["status"], tone="danger" if row["status"] == "error" else "warning"),
            scope_badge(row["gender_path"]),
            esc(row["content"][:90]),
            f'<span class="ltr-num">{esc(str(row["created_at"])[:16])}</span>',
        ]
        for row in ai_repo.recent_failures(8)
    ]

    engine = join(
        [
            '<div class="list-rows">',
            _row("ספק", esc(provider.name) + (" (מוק)" if provider.is_mock else "")),
            _row("מודל", f'<span class="ltr-num">{esc(provider.health().get("model", "—"))}</span>'),
            _row("זמן תגובה ממוצע", f'<span class="ltr-num">{stats["avg_latency_ms"]} ms</span>'),
            _row("מכסה יומית למשתמש", f"{settings.ai_daily_message_limit} הודעות"),
            _row("שיחות פתוחות", str(stats["conversations"])),
            "</div>",
            '<p class="admin-note" style="margin-top:var(--space-3)">',
            "למנוע אין הרשאות ניהול: הוא אינו מוחק משתמשים, אינו משנה מנויים ואינו נוגע בתוכן. ",
            "הוא קורא רק תוכן מאושר של המסלול שממנו נשאלה השאלה, ותשובות שנשמעות רפואיות נחסמות לפני שהן נשלחות.",
            "</p>",
        ]
    )

    body = join(
        [
            '<div class="stack-lg">',
            mode_flag(),
            '<div class="grid grid-4">',
            stat_card("בקשות (30 יום)", f"{stats['requests']:,}", icon_name="sparkles"),
            stat_card("תשובות", f"{stats['responses']:,}", icon_name="check", tone="success"),
            stat_card("נחסמו במדיניות", f"{stats['blocked']:,}", icon_name="shield", tone="warning"),
            stat_card("שגיאות", f"{stats['errors']:,}", icon_name="info", tone="female" if stats["errors"] else "success"),
            "</div>",
            '<div class="grid split">',
            card(card_header("שאלות נפוצות", icon_name="sparkles")
                 + table(["שאלה", "פעמים", "אחרון"], question_rows, empty_message="אין עדיין שיחות")),
            card(card_header("הגדרות מנוע", icon_name="settings") + engine),
            "</div>",
            card(card_header("תשובות שנחסמו או נכשלו", icon_name="shield")
                 + table(["סטטוס", "מסלול", "תוכן", "מועד"], failure_rows, empty_message="אין כשלים להצגה")),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="AI & אוטומציה", context=ctx, active="ai", csrf_token=request.csrf_token))


# ------------------------------------------------------------ analytics -----
def analytics_page(request: Request) -> Response:
    ctx = require_admin(request)
    funnel = insights.funnel(list(analytics.FUNNEL), days=90)
    top = funnel[0]["total"] if funnel and funnel[0]["total"] else 0

    funnel_rows = []
    for step in funnel:
        share = round(100 * step["total"] / top) if top else 0
        funnel_rows.append(
            '<div class="progress" style="margin-bottom:var(--space-3)">'
            f'<div class="progress-head"><span>{esc(analytics.label(step["name"]))}</span>'
            f'<span>{step["total"]} · {share}%</span></div>'
            f'<div class="progress-track"><div class="progress-fill" style="width:{share}%"></div></div></div>'
        )

    count_rows = [
        [esc(analytics.label(row["name"])), str(row["total"]), str(row["female"] or 0), str(row["male"] or 0)]
        for row in insights.event_counts(30)
    ]
    audit_rows = [
        [
            esc(row["action"]),
            esc(row.get("actor_name") or row.get("actor_email") or "—"),
            f'{esc(row["entity_type"])} #{esc(row["entity_id"])}',
            f'<span class="ltr-num">{esc(str(row["created_at"])[:16])}</span>',
        ]
        for row in insights.list_audit(20)
    ]

    body = join(
        [
            '<div class="stack-lg">',
            '<div class="grid split">',
            card(card_header("משפך המרה", subtitle="90 הימים האחרונים", icon_name="chart")
                 + (join(funnel_rows) or '<p class="muted small">אין עדיין נתונים.</p>')),
            card(card_header("אירועים לפי מסלול", subtitle="30 הימים האחרונים", icon_name="users")
                 + table(["אירוע", "סה״כ", "נשים", "גברים"], count_rows, empty_message="אין עדיין אירועים")),
            "</div>",
            card(card_header("יומן ביקורת", subtitle="פעולות ניהול אחרונות", icon_name="shield")
                 + table(["פעולה", "מנהל", "ישות", "מועד"], audit_rows, empty_message="אין רישומים")),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="דוחות וסטטיסטיקות", context=ctx, active="analytics", csrf_token=request.csrf_token))


# ------------------------------------------------------------- settings -----
def settings_page(request: Request) -> Response:
    ctx = require_admin(request)
    settings = get_settings()
    ai_provider = get_ai_provider()
    payment_provider = get_payment_provider()

    system = join(
        [
            '<div class="list-rows">',
            _row("סביבה", f'<span class="ltr-num">{esc(settings.env)}</span>',
                 badge(settings.mode, tone="success" if settings.mode == "production" else "warning")),
            _row("ספק AI", f'<span class="ltr-num">{esc(ai_provider.name)}</span>',
                 badge("מוק" if ai_provider.is_mock else "חי", tone="warning" if ai_provider.is_mock else "success")),
            _row("ספק תשלומים", f'<span class="ltr-num">{esc(payment_provider.name)}</span>',
                 badge("מוק" if payment_provider.is_mock else "חי", tone="warning" if payment_provider.is_mock else "success")),
            _row("אחסון קבצים", f'<span class="ltr-num">{esc(settings.storage_provider)}</span>'),
            _row("שם המותג", esc(settings.brand_name)),
            "</div>",
            '<p class="admin-note" style="margin-top:var(--space-3)">',
            "הערכים נקבעים במשתני סביבה ואינם ניתנים לשינוי מהדפדפן — כך אי אפשר להפעיל בטעות ספק אמיתי מתוך ממשק הניהול.",
            "</p>",
        ]
    )

    policy = join(
        [
            '<div class="list-rows">',
            '<div class="list-row"><div class="list-row-main"><p class="list-row-title">הפרדת מסלולים</p>'
            '<p class="list-row-meta">נאכפת בשרת בכל בקשה ובכל שאילתת תוכן</p></div>'
            + badge("פעיל", tone="success") + "</div>",
            '<div class="list-row"><div class="list-row-main"><p class="list-row-title">יומן ביקורת</p>'
            '<p class="list-row-meta">כל פעולת ניהול נרשמת עם מזהה המנהל</p></div>'
            + badge("פעיל", tone="success") + "</div>",
            '<div class="list-row"><div class="list-row-main"><p class="list-row-title">הגבלת קצב</p>'
            f'<p class="list-row-meta">{settings.rate_limit_per_minute} בקשות לדקה לכתובת IP</p></div>'
            + badge("פעיל", tone="success") + "</div>",
            '<div class="list-row"><div class="list-row-main"><p class="list-row-title">אימות webhook</p>'
            '<p class="list-row-meta">תשלום מופעל רק מול חתימה תקינה של הספק</p></div>'
            + badge("פעיל", tone="success") + "</div>",
            "</div>",
        ]
    )

    coach_cards = []
    for coach in content_repo.list_coaches():
        coach_cards.append(
            card(
                f'<div class="row-between"><div><h3 class="card-title">{esc(coach.name)}</h3></div>'
                f"{scope_badge(coach.gender_path.value)}</div>"
                + join(
                    [
                        f'<form method="post" action="/admin/coaches/{coach.id}" class="stack" style="margin-top:var(--space-4)">',
                        csrf_input(request.csrf_token),
                        text_input("name", label="שם", value=coach.name),
                        textarea("bio", label="ביוגרפיה", value=coach.bio, rows=2),
                        text_input("photo_url", label="תמונה", value=coach.photo_url),
                        button("שמירה", type_="submit", variant="secondary", size="sm"),
                        "</form>",
                    ]
                ),
                css_class="card-tight",
            )
        )
    coaches_block = (
        f'<div class="grid grid-2">{join(coach_cards)}</div>'
        if coach_cards
        else card(empty_state("לא הוגדרו מאמנים", "אפשר להוסיף מאמנים דרך ה‑seed.", icon_name="users"))
    )

    body = join(
        [
            '<div class="stack-lg">',
            '<div class="grid split">',
            card(card_header("מצב המערכת", icon_name="shield") + system),
            card(card_header("מדיניות והרשאות", icon_name="users") + policy),
            "</div>",
            "<section>",
            card_header("מאמנים", subtitle="כל מסלול מציג את המאמן/ת שלו"),
            coaches_block,
            "</section>",
            "</div>",
        ]
    )
    return html(admin_layout(body, title="הגדרות מערכת", context=ctx, active="settings", csrf_token=request.csrf_token))


def coach_update(request: Request) -> Response:
    ctx = require_admin(request)
    coach_id = request.int_param("coach_id")
    if content_repo.get_coach(coach_id) is None:
        raise NotFound()
    data = request.data()
    content_repo.update_coach(
        coach_id,
        name=str(data.get("name", ""))[:120],
        bio=str(data.get("bio", ""))[:600],
        photo_url=str(data.get("photo_url", ""))[:500],
    )
    insights.record_audit(ctx.user.id, "coach_updated", entity_type="coach", entity_id=str(coach_id), ip_address=request.remote_addr)
    return flash_redirect("/admin/settings", "פרטי המאמן עודכנו")


def register(router: Router) -> None:
    router.get("/admin/ai", ai_page)
    router.get("/admin/analytics", analytics_page)
    router.get("/admin/settings", settings_page)
    router.post("/admin/coaches/<int:coach_id>", coach_update)
