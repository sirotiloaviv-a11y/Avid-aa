"""The admin console (22-28, 46).

Every handler starts with ``require_admin``. Admin reads use the ``admin_*``
repository functions, which are the only ones that cross the path boundary —
and they are unreachable without the role check that opens this module.
"""

from __future__ import annotations

from ...core.errors import NotFound
from ...core.request import Request
from ...core.response import Response, html
from ...core.router import Router
from ...config import get_settings
from ...db.repositories import (
    ai as ai_repo,
    billing as billing_repo,
    content as content_repo,
    food as food_repo,
    insights,
    users as users_repo,
)
from ...domain.roles import Role
from ...services.authorization import require_admin
from ..support import flash_redirect
from ..ui.charts import bar_chart, donut_chart, line_chart
from ..ui.components import (
    badge,
    button,
    card,
    card_header,
    csrf_input,
    select,
    stat_card,
    table,
)
from ..ui.icons import icon
from ..ui.layouts import admin_layout
from ..ui.primitives import esc, join, money

_SCOPE_OPTIONS = (("female", "נשים"), ("male", "גברים"), ("all", "כל המסלולים"))


def _scope_badge(scope: str) -> str:
    return {
        "female": badge("נשים", tone="female"),
        "male": badge("גברים", tone="male"),
        "all": badge("כולם", tone="soft"),
    }.get(scope, badge(scope, tone="soft"))


def _mode_flag() -> str:
    settings = get_settings()
    if settings.mode == "production":
        return ""
    return (
        f'<span class="mode-flag">{icon("info", size=14)} מצב {esc(settings.mode)} — '
        f"AI: {esc(settings.ai_provider)}, תשלומים: {esc(settings.payment_provider)}</span>"
    )


# -------------------------------------------------------------- overview ----
def overview(request: Request) -> Response:
    ctx = require_admin(request)
    distribution = users_repo.gender_distribution()
    female = distribution.get("female", 0)
    male = distribution.get("male", 0)
    total_users = users_repo.count_users()
    active_users = users_repo.active_user_count(7)
    revenue = billing_repo.revenue_cents(30)
    active_subs = billing_repo.active_subscription_count()

    signups = users_repo.signups_by_day(14)
    growth = line_chart(
        [
            {"name": "נשים", "values": [int(row["female"]) for row in signups], "tone": "female"},
            {"name": "גברים", "values": [int(row["male"]) for row in signups], "tone": "male"},
        ],
        [str(row["day"])[5:] for row in signups],
    ) if signups else '<div class="chart-empty">אין עדיין הרשמות להצגה</div>'

    split = donut_chart(
        [
            {"label": "נשים", "value": female, "tone": "female"},
            {"label": "גברים", "value": male, "tone": "male"},
        ],
        center_value=f"{female + male:,}",
        center_label="משתמשים",
    )

    popular = content_repo.popular_videos(5)
    popular_rows = join(
        [
            f'<div class="list-row"><div class="list-row-main">'
            f'<p class="list-row-title">{esc(row["title"])}</p>'
            f'<p class="list-row-meta">{esc(content_repo.CATEGORY_LABELS.get(row["category"], row["category"]))} · '
            f'{row["views"]} צפיות</p></div>{_scope_badge(row["gender_path"])}</div>'
            for row in popular
        ]
    ) or '<p class="muted small">אין עדיין נתוני צפייה.</p>'

    recent_users = users_repo.list_users(limit=6)
    users_rows = [
        [
            f'<div class="table-user"><div><p class="table-user-name">{esc(row["name"] or "—")}</p>'
            f'<p class="table-user-email">{esc(row["email"])}</p></div></div>',
            _scope_badge(row.get("gender_path") or "all"),
            badge(row.get("subscription_status") or "ללא", tone="success" if row.get("subscription_status") == "active" else "soft"),
            f'<span class="ltr-num">{esc(str(row["created_at"])[:10])}</span>',
        ]
        for row in recent_users
    ]

    payments = billing_repo.recent_payments(6)
    payment_rows = [
        [
            esc(row["user_name"] or row["user_email"]),
            f'<span class="ltr-num">{esc(money(int(row["amount_cents"])))}</span>',
            badge("שולם" if row["status"] == "succeeded" else row["status"],
                  tone="success" if row["status"] == "succeeded" else "warning"),
            f'<span class="ltr-num">{esc(str(row["created_at"])[:10])}</span>',
        ]
        for row in payments
    ]

    tasks = _open_tasks()

    body = f"""
    <div class="stack-lg">
      {_mode_flag()}
      <div class="grid grid-4">
        {stat_card("משתמשים רשומים", f"{total_users:,}", icon_name="users", tone="brand", caption="סה״כ")}
        {stat_card("פעילים ב‑7 ימים", f"{active_users:,}", icon_name="flame", tone="success", caption="נכנסו למערכת")}
        {stat_card("הכנסות 30 יום", money(revenue), icon_name="credit", tone="warning", caption="תשלומים שאושרו")}
        {stat_card("מנויים פעילים", f"{active_subs:,}", icon_name="chart", tone="male", caption="מחזור חוזר")}
      </div>

      <div class="grid split">
        {card(card_header("מגמת הרשמות", subtitle="14 הימים האחרונים", icon_name="chart") + growth)}
        {card(card_header("חלוקת מסלולים", icon_name="users") + split)}
      </div>

      <div class="grid split">
        {card(card_header("תוכן פופולרי", icon_name="video") + f'<div class="list-rows">{popular_rows}</div>')}
        {card(card_header("משימות פתוחות", icon_name="info") + tasks)}
      </div>

      <div class="grid split">
        {card(card_header("משתמשים אחרונים", icon_name="users",
                          action=button("לכל המשתמשים", href="/admin/users", variant="ghost", size="sm", icon_end="arrow"))
              + table(["משתמש", "מסלול", "מנוי", "הצטרפות"], users_rows, empty_message="אין עדיין משתמשים"))}
        {card(card_header("תשלומים אחרונים", icon_name="credit",
                          action=button("לניהול מנויים", href="/admin/billing", variant="ghost", size="sm", icon_end="arrow"))
              + table(["משתמש", "סכום", "סטטוס", "תאריך"], payment_rows, empty_message="אין עדיין תשלומים"))}
      </div>
    </div>
    """
    return html(
        admin_layout(body, title="דשבורד ניהולי", subtitle="סקירה כללית של העסק", context=ctx,
                     active="overview", csrf_token=request.csrf_token)
    )


def _open_tasks() -> str:
    unpublished = len(content_repo.admin_list_videos(published="0", limit=100))
    unapproved = len(food_repo.admin_list_recipes(approved="0", limit=100))
    past_due = billing_repo.subscription_breakdown().get("past_due", 0)
    ai_errors = ai_repo.usage_stats(7)["errors"]
    rows = (
        ("סרטונים שממתינים לפרסום", unpublished, "warning", "/admin/videos?published=0"),
        ("מתכונים שממתינים לאישור", unapproved, "warning", "/admin/programs?tab=recipes&approved=0"),
        ("מנויים בכשל תשלום", past_due, "danger", "/admin/billing"),
        ("שגיאות AI בשבוע האחרון", ai_errors, "danger" if ai_errors else "success", "/admin/ai"),
    )
    return '<div class="task-list">' + join(
        [
            f'<a class="task-item" href="{esc(href)}"><span class="task-dot is-{esc(tone)}"></span>'
            f'<span class="grow">{esc(label)}</span><strong>{count}</strong></a>'
            for label, count, tone, href in rows
        ]
    ) + "</div>"


# ----------------------------------------------------------------- users ----
def users_list(request: Request) -> Response:
    ctx = require_admin(request)
    gender = request.get("gender")
    role = request.get("role")
    search = request.get("q")
    subscription = request.get("subscription")

    rows = users_repo.list_users(
        gender_path=gender, role=role, search=search, subscription_status=subscription, limit=100
    )
    table_rows = [
        [
            f'<div class="table-user"><div><p class="table-user-name">{esc(row["name"] or "—")}</p>'
            f'<p class="table-user-email">{esc(row["email"])}</p></div></div>',
            _scope_badge(row.get("gender_path") or "all"),
            badge(Role.parse(row["role"]).label, tone="brand" if row["role"] == "admin" else "soft"),
            badge(row.get("subscription_status") or "ללא", tone="success" if row.get("subscription_status") == "active" else "soft"),
            f'<span class="ltr-num">{esc(str(row["created_at"])[:10])}</span>',
            f'<span class="ltr-num">{esc(str(row.get("last_active_at") or "—")[:10])}</span>',
            button("צפייה", href=f'/admin/users/{row["id"]}', variant="ghost", size="sm"),
        ]
        for row in rows
    ]

    filters = f"""
    <form class="admin-filters" method="get" action="/admin/users">
      <div class="field grow" style="min-width:220px">
        <input class="input" type="search" name="q" value="{esc(search)}" placeholder="חיפוש לפי שם או אימייל">
      </div>
      {select("gender", _SCOPE_OPTIONS[:2], value=gender, placeholder="כל המסלולים", data_autosubmit=True)}
      {select("subscription", (("active", "מנוי פעיל"), ("pending", "ממתין"), ("past_due", "כשל תשלום"), ("cancelled", "בוטל"), ("none", "ללא מנוי")), value=subscription, placeholder="כל המנויים", data_autosubmit=True)}
      {button("סינון", type_="submit", variant="secondary")}
    </form>
    """

    body = f"""
    <div class="stack-lg">
      <div class="admin-toolbar">
        {filters}
        <span class="muted small">{len(rows)} תוצאות</span>
      </div>
      {table(["משתמש", "מסלול", "תפקיד", "מנוי", "הצטרפות", "פעילות אחרונה", ""], table_rows,
             empty_message="לא נמצאו משתמשים בסינון הזה")}
    </div>
    """
    return html(
        admin_layout(body, title="משתמשים", subtitle="ניהול חשבונות", context=ctx, active="users",
                     csrf_token=request.csrf_token)
    )


def user_detail(request: Request) -> Response:
    ctx = require_admin(request)
    user = users_repo.get_user(request.int_param("user_id"))
    if user is None:
        raise NotFound()
    profile = users_repo.get_profile(user.id)
    subscription = billing_repo.latest_subscription(user.id)
    completed = content_repo.completed_count(user.id)

    body = f"""
    <div class="grid split">
      {card(card_header("פרטי משתמש", icon_name="users") + f'''
        <div class="list-rows">
          <div class="list-row"><div class="list-row-main"><p class="list-row-meta">שם</p>
            <p class="list-row-title">{esc(user.name or "—")}</p></div></div>
          <div class="list-row"><div class="list-row-main"><p class="list-row-meta">אימייל</p>
            <p class="list-row-title">{esc(user.email)}</p></div></div>
          <div class="list-row"><div class="list-row-main"><p class="list-row-meta">מסלול</p>
            <p class="list-row-title">{esc(user.gender_path.label if user.gender_path else "לא נבחר")}</p></div></div>
          <div class="list-row"><div class="list-row-main"><p class="list-row-meta">שאלון</p>
            <p class="list-row-title">{"הושלם" if user.onboarding_completed else "לא הושלם"}</p></div></div>
          <div class="list-row"><div class="list-row-main"><p class="list-row-meta">אימונים שהושלמו</p>
            <p class="list-row-title">{completed}</p></div></div>
        </div>
      ''')}
      <div class="stack">
        {card(card_header("מנוי", icon_name="credit") + (f'''
          <div class="list-rows">
            <div class="list-row"><div class="list-row-main"><p class="list-row-meta">מסלול</p>
              <p class="list-row-title">{esc(subscription.plan_code)}</p></div>
              {badge(subscription.status.label, tone="success" if subscription.is_active else "warning")}</div>
            <div class="list-row"><div class="list-row-main"><p class="list-row-meta">בתוקף עד</p>
              <p class="list-row-title ltr-num">{esc((subscription.current_period_end or "—")[:10])}</p></div></div>
          </div>
        ''' if subscription else '<p class="muted small">אין מנוי.</p>'))}
        {card(card_header("פעולות ניהול", icon_name="shield") + f'''
          <form method="post" action="/admin/users/{user.id}/status" class="row">
            {csrf_input(request.csrf_token)}
            <input type="hidden" name="status" value="{"suspended" if user.status == "active" else "active"}">
            {button("השעיית חשבון" if user.status == "active" else "החזרת חשבון לפעילות", type_="submit", variant="secondary")}
          </form>
          <p class="admin-note" style="margin-top:var(--space-3)">
            כל פעולה נרשמת ביומן הביקורת עם מזהה המנהל שביצע אותה.
          </p>
        ''')}
      </div>
    </div>
    """
    return html(
        admin_layout(body, title=user.name or user.email, subtitle="כרטיס משתמש", context=ctx,
                     active="users", csrf_token=request.csrf_token)
    )


def user_status(request: Request) -> Response:
    ctx = require_admin(request)
    user_id = request.int_param("user_id")
    status = str(request.data().get("status", "active"))
    if status not in {"active", "suspended"}:
        raise NotFound()
    users_repo.set_status(user_id, status)
    if status == "suspended":
        users_repo.delete_user_sessions(user_id)
    insights.record_audit(
        ctx.user.id, "user_status_changed", entity_type="user", entity_id=str(user_id),
        details={"status": status}, ip_address=request.remote_addr,
    )
    return flash_redirect(f"/admin/users/{user_id}", "סטטוס המשתמש עודכן")


# --------------------------------------------------------------- billing ----
def billing_page(request: Request) -> Response:
    ctx = require_admin(request)
    breakdown = billing_repo.subscription_breakdown()
    revenue_days = billing_repo.revenue_by_day(14)
    revenue_chart = bar_chart(
        [{"label": str(row["day"])[5:], "value": int(row["total"] or 0) / 100} for row in revenue_days]
    ) if revenue_days else '<div class="chart-empty">אין עדיין תשלומים</div>'

    payment_rows = [
        [
            esc(row["user_name"] or row["user_email"]),
            _scope_badge(row.get("gender_path") or "all"),
            f'<span class="ltr-num">{esc(money(int(row["amount_cents"])))}</span>',
            badge(row["status"], tone="success" if row["status"] == "succeeded" else "warning"),
            esc(row["provider"]),
            f'<span class="ltr-num">{esc(str(row["created_at"])[:16])}</span>',
        ]
        for row in billing_repo.recent_payments(40)
    ]

    status_cards = join(
        [
            stat_card(label, str(breakdown.get(key, 0)), icon_name="credit",
                      tone="success" if key == "active" else "warning")
            for key, label in (("active", "פעילים"), ("pending", "ממתינים"), ("past_due", "כשל תשלום"), ("cancelled", "בוטלו"))
        ]
    )

    body = f"""
    <div class="stack-lg">
      <div class="grid grid-4">{status_cards}</div>
      {card(card_header("הכנסות יומיות", subtitle="14 הימים האחרונים (₪)", icon_name="chart") + revenue_chart)}
      {card(card_header("תשלומים", icon_name="credit")
            + table(["משתמש", "מסלול", "סכום", "סטטוס", "ספק", "מועד"], payment_rows,
                    empty_message="אין עדיין תשלומים במערכת"))}
    </div>
    """
    return html(
        admin_layout(body, title="מנויים ותשלומים", context=ctx, active="billing", csrf_token=request.csrf_token)
    )


def register(router: Router) -> None:
    router.get("/admin", overview)
    router.get("/admin/users", users_list)
    router.get("/admin/users/<int:user_id>", user_detail)
    router.post("/admin/users/<int:user_id>/status", user_status)
    router.get("/admin/billing", billing_page)
