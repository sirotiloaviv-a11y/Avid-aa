"""Admin content management: videos, programs, recipes (25, 26, 27).

Split from the overview module because content CRUD is the part that grows;
keeping it separate stops one admin file from becoming the thing rule 42 warns
about. Every write is audited with the acting admin's id.
"""

from __future__ import annotations

from ...core.errors import NotFound
from ...core.request import Request
from ...core.response import Response, html
from ...core.router import Router
from ...db.repositories import content as content_repo, food as food_repo, insights
from ...domain.gender import ContentScope
from ...services.authorization import require_admin
from ..support import flash_redirect
from ..ui.components import (
    alert,
    badge,
    button,
    card,
    card_header,
    checkbox,
    csrf_input,
    empty_state,
    select,
    table,
    tabs,
    text_input,
    textarea,
)
from ..ui.layouts import admin_layout
from ..ui.primitives import esc, join

SCOPE_OPTIONS = (("female", "נשים"), ("male", "גברים"), ("all", "כל המסלולים"))
EQUIPMENT_OPTIONS = (
    ("mat", "מזרן"),
    ("dumbbells", "משקולות"),
    ("bands", "גומיות"),
    ("kettlebell", "קטלבל"),
    ("barbell", "מוט"),
    ("pullup_bar", "מתח"),
)


def scope_badge(scope: str) -> str:
    return {
        "female": badge("נשים", tone="female"),
        "male": badge("גברים", tone="male"),
        "all": badge("כולם", tone="soft"),
    }.get(scope, badge(scope, tone="soft"))


def content_tabs(active: str) -> str:
    return tabs(
        [
            ("סרטונים", "/admin/videos", active == "videos"),
            ("תוכניות", "/admin/programs", active == "programs"),
            ("מתכונים", "/admin/programs?tab=recipes", active == "recipes"),
        ]
    )


def _one(form: dict, key: str, default: str = "") -> str:
    return (form.get(key, [default])[0] or default).strip()


# ---------------------------------------------------------------- videos ----
def _video_form(request: Request, video=None) -> str:
    coaches = content_repo.list_coaches()
    selected = set(video.equipment if video else [])
    action = f"/admin/videos/{video.id}" if video else "/admin/videos"
    equipment_boxes = join(
        [checkbox("equipment", label, value=key, checked=key in selected) for key, label in EQUIPMENT_OPTIONS]
    )
    coach_options = tuple((str(coach.id), coach.name) for coach in coaches)
    parts = [
        f'<form method="post" action="{esc(action)}" class="admin-form-grid" data-guard>',
        csrf_input(request.csrf_token),
        text_input("title", label="כותרת", value=video.title if video else "", required=True),
        textarea("description", label="תיאור", value=video.description if video else "", rows=3),
        '<div class="grid grid-2">',
        text_input("duration", label="משך (דקות)", type_="number", value=str(video.duration) if video else "30", required=True),
        select("difficulty", content_repo.DIFFICULTIES, label="רמת קושי", value=video.difficulty if video else "beginner"),
        "</div>",
        '<div class="grid grid-2">',
        select("category", content_repo.VIDEO_CATEGORIES, label="קטגוריה", value=video.category if video else "full_body"),
        select("gender_path", SCOPE_OPTIONS, label="מסלול", value=video.gender_path.value if video else "female"),
        "</div>",
        '<div class="grid grid-2">',
        select("coach_id", coach_options, label="מאמן/ת", value=str(video.coach_id) if video and video.coach_id else "", placeholder="ללא"),
        text_input("thumbnail_url", label="תמונה ממוזערת", value=video.thumbnail_url if video else "",
                   hint="נשמרת דרך שכבת האחסון. אפשר להשאיר ריק — יוצג תחליף מעוצב."),
        "</div>",
        text_input("video_url", label="כתובת קובץ הווידאו", value=video.video_url if video else "",
                   hint="בפרודקשן הכתובת מגיעה מספק האחסון."),
        f'<div class="field"><span class="field-label">ציוד נדרש</span><div class="row">{equipment_boxes}</div></div>',
        text_input("tags", label="תגיות", value=", ".join(video.tags) if video else "", hint="מופרדות בפסיק"),
        f'<div class="row">{checkbox("published", "מפורסם", checked=bool(video.published) if video else False)}</div>',
        button("שמירת סרטון" if video else "יצירת סרטון", type_="submit", variant="primary"),
        "</form>",
    ]
    return join(parts)


def videos_page(request: Request) -> Response:
    ctx = require_admin(request)
    gender = request.get("gender")
    published = request.get("published")
    search = request.get("q")
    videos = content_repo.admin_list_videos(gender_path=gender, published=published, search=search, limit=100)

    rows = [
        [
            esc(video.title),
            scope_badge(video.gender_path.value),
            esc(content_repo.CATEGORY_LABELS.get(video.category, video.category)),
            esc(content_repo.DIFFICULTY_LABELS.get(video.difficulty, video.difficulty)),
            f"{video.duration} דק׳",
            badge("מפורסם", tone="success") if video.published else badge("טיוטה", tone="warning"),
            button("עריכה", href=f"/admin/videos/{video.id}/edit", variant="ghost", size="sm"),
        ]
        for video in videos
    ]

    filters = join(
        [
            '<form class="admin-filters" method="get" action="/admin/videos">',
            f'<div class="field" style="min-width:200px"><input class="input" type="search" name="q" value="{esc(search)}" placeholder="חיפוש לפי כותרת"></div>',
            select("gender", SCOPE_OPTIONS, value=gender, placeholder="כל המסלולים"),
            select("published", (("1", "מפורסם"), ("0", "טיוטה")), value=published, placeholder="כל הסטטוסים"),
            button("סינון", type_="submit", variant="secondary"),
            "</form>",
        ]
    )

    body = join(
        [
            '<div class="stack-lg">',
            content_tabs("videos"),
            f'<div class="admin-toolbar">{filters}<span class="muted small">{len(videos)} סרטונים</span></div>',
            table(["כותרת", "מסלול", "קטגוריה", "רמה", "משך", "סטטוס", ""], rows, empty_message="אין סרטונים בסינון הזה"),
            card(card_header("העלאת סרטון חדש", subtitle="כל פריט תוכן חייב שיוך למסלול", icon_name="video") + _video_form(request)),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="תוכן וסרטונים", context=ctx, active="videos", csrf_token=request.csrf_token))


def _video_payload(request: Request) -> dict:
    form = request.form()
    tags = [tag.strip() for tag in _one(form, "tags").split(",") if tag.strip()]
    scope = ContentScope.parse(_one(form, "gender_path", "female")) or ContentScope.FEMALE
    difficulty = _one(form, "difficulty", "beginner")
    category = _one(form, "category", "full_body")
    try:
        duration = max(0, min(300, int(_one(form, "duration", "0") or 0)))
    except ValueError:
        duration = 0
    coach_raw = _one(form, "coach_id")
    return {
        "title": _one(form, "title")[:160],
        "description": _one(form, "description")[:2000],
        "thumbnail_url": _one(form, "thumbnail_url")[:500],
        "video_url": _one(form, "video_url")[:500],
        "duration": duration,
        "difficulty": difficulty if difficulty in content_repo.DIFFICULTY_LABELS else "beginner",
        "category": category if category in content_repo.CATEGORY_LABELS else "full_body",
        "gender_path": scope.value,
        "coach_id": int(coach_raw) if coach_raw.isdigit() else None,
        "equipment": form.get("equipment", []),
        "tags": tags,
        "published": bool(form.get("published")),
    }


def video_create(request: Request) -> Response:
    ctx = require_admin(request)
    payload = _video_payload(request)
    if not payload["title"]:
        return flash_redirect("/admin/videos", "צריך כותרת לסרטון", tone="error")
    video_id = content_repo.create_video(**payload)
    insights.record_audit(
        ctx.user.id, "video_created", entity_type="video", entity_id=str(video_id),
        details={"title": payload["title"], "gender_path": payload["gender_path"]},
        ip_address=request.remote_addr,
    )
    return flash_redirect("/admin/videos", "הסרטון נוצר")


def video_edit(request: Request) -> Response:
    ctx = require_admin(request)
    video = content_repo.get_video(request.int_param("video_id"))
    if video is None:
        raise NotFound()
    delete_form = join(
        [
            '<p class="muted small">מחיקה מסירה את הסרטון גם מהתוכניות שמכילות אותו.</p>',
            f'<form method="post" action="/admin/videos/{video.id}/delete" style="margin-top:var(--space-3)"',
            ' onsubmit="return confirm(\'למחוק את הסרטון?\');">',
            csrf_input(request.csrf_token),
            button("מחיקת הסרטון", type_="submit", variant="danger"),
            "</form>",
        ]
    )
    body = join(
        [
            '<div class="stack-lg">',
            card(card_header(f"עריכת סרטון: {video.title}", icon_name="edit") + _video_form(request, video)),
            card(card_header("מחיקה", icon_name="trash") + delete_form),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="עריכת סרטון", context=ctx, active="videos", csrf_token=request.csrf_token))


def video_update(request: Request) -> Response:
    ctx = require_admin(request)
    video_id = request.int_param("video_id")
    if content_repo.get_video(video_id) is None:
        raise NotFound()
    content_repo.update_video(video_id, **_video_payload(request))
    insights.record_audit(ctx.user.id, "video_updated", entity_type="video", entity_id=str(video_id), ip_address=request.remote_addr)
    return flash_redirect("/admin/videos", "הסרטון עודכן")


def video_delete(request: Request) -> Response:
    ctx = require_admin(request)
    video_id = request.int_param("video_id")
    content_repo.delete_video(video_id)
    insights.record_audit(ctx.user.id, "video_deleted", entity_type="video", entity_id=str(video_id), ip_address=request.remote_addr)
    return flash_redirect("/admin/videos", "הסרטון נמחק")


# -------------------------------------------------------------- programs ----
def programs_page(request: Request) -> Response:
    ctx = require_admin(request)
    if request.get("tab") == "recipes":
        return _recipes_tab(request, ctx)

    programs = content_repo.admin_list_programs(request.get("gender"))
    rows = [
        [
            esc(program.name),
            scope_badge(program.gender_path.value),
            f"{program.duration_weeks} שבועות",
            esc(content_repo.DIFFICULTY_LABELS.get(program.difficulty, program.difficulty)),
            badge("מפורסמת", tone="success") if program.published else badge("טיוטה", tone="warning"),
            button("צפייה", href=f"/admin/programs/{program.id}", variant="ghost", size="sm"),
        ]
        for program in programs
    ]
    form = join(
        [
            '<form method="post" action="/admin/programs" class="admin-form-grid" data-guard>',
            csrf_input(request.csrf_token),
            text_input("name", label="שם התוכנית", required=True),
            textarea("description", label="תיאור", rows=2),
            '<div class="grid grid-2">',
            text_input("duration_weeks", label="משך (שבועות)", type_="number", value="4"),
            select("difficulty", content_repo.DIFFICULTIES, label="רמה", value="beginner"),
            "</div>",
            '<div class="grid grid-2">',
            select("gender_path", SCOPE_OPTIONS, label="מסלול", value="female"),
            text_input("goal_tags", label="יעדים", hint="מופרדים בפסיק, למשל: tone, strength"),
            "</div>",
            f'<div class="row">{checkbox("published", "מפורסמת")}</div>',
            button("יצירת תוכנית", type_="submit", variant="primary"),
            "</form>",
        ]
    )
    body = join(
        [
            '<div class="stack-lg">',
            content_tabs("programs"),
            table(["שם", "מסלול", "משך", "רמה", "סטטוס", ""], rows, empty_message="אין עדיין תוכניות"),
            card(card_header("תוכנית חדשה", icon_name="program") + form),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="תוכניות ומתכונים", context=ctx, active="programs", csrf_token=request.csrf_token))


def program_create(request: Request) -> Response:
    ctx = require_admin(request)
    form = request.form()
    name = _one(form, "name")[:160]
    if not name:
        return flash_redirect("/admin/programs", "צריך שם לתוכנית", tone="error")
    scope = ContentScope.parse(_one(form, "gender_path", "female")) or ContentScope.FEMALE
    try:
        weeks = max(1, min(52, int(_one(form, "duration_weeks", "4") or 4)))
    except ValueError:
        weeks = 4
    program_id = content_repo.create_program(
        name=name,
        description=_one(form, "description")[:1000],
        gender_path=scope.value,
        duration_weeks=weeks,
        difficulty=_one(form, "difficulty", "beginner"),
        goal_tags=[tag.strip() for tag in _one(form, "goal_tags").split(",") if tag.strip()],
        published=bool(form.get("published")),
    )
    insights.record_audit(ctx.user.id, "program_created", entity_type="program", entity_id=str(program_id), ip_address=request.remote_addr)
    return flash_redirect("/admin/programs", "התוכנית נוצרה")


def program_detail(request: Request) -> Response:
    ctx = require_admin(request)
    program = content_repo.get_program(request.int_param("program_id"))
    if program is None:
        raise NotFound()

    day_cards = []
    for day in program.days:
        videos = join(
            [
                f'<div class="list-row"><div class="list-row-main"><p class="list-row-title">{esc(video.title)}</p>'
                f'<p class="list-row-meta">{video.duration} דקות</p></div></div>'
                for video in day.videos
            ]
        )
        head = (
            f'<div class="row-between"><div><p class="card-subtitle">יום {day.day_number}</p>'
            f'<h3 class="card-title">{esc(day.title)}</h3></div>'
            + (badge("מנוחה", tone="soft") if day.is_rest else badge(f"{len(day.videos)} סרטונים", tone="outline"))
            + "</div>"
        )
        listing = f'<div class="list-rows" style="margin-top:var(--space-3)">{videos}</div>' if videos else ""
        day_cards.append(card(head + listing, css_class="card-tight"))

    header = card(
        f'<div class="row-between"><div><h2>{esc(program.name)}</h2>'
        f'<p class="muted">{esc(program.description)}</p></div>{scope_badge(program.gender_path.value)}</div>'
    )
    grid = (
        f'<div class="grid grid-2">{join(day_cards)}</div>'
        if day_cards
        else card(empty_state("אין ימים בתוכנית", "אפשר להוסיף ימים דרך ה‑seed או ה‑API.", icon_name="program"))
    )
    return html(
        admin_layout(f'<div class="stack-lg">{header}{grid}</div>', title=program.name, context=ctx,
                     active="programs", csrf_token=request.csrf_token)
    )


# --------------------------------------------------------------- recipes ----
def _recipes_tab(request: Request, ctx) -> Response:
    recipes = food_repo.admin_list_recipes(
        gender_path=request.get("gender"), approved=request.get("approved"), search=request.get("q"), limit=100
    )
    rows = []
    for recipe in recipes:
        toggle = join(
            [
                f'<form method="post" action="/admin/recipes/{recipe.id}/approve">',
                csrf_input(request.csrf_token),
                f'<input type="hidden" name="approved" value="{0 if recipe.approved else 1}">',
                button("ביטול אישור" if recipe.approved else "אישור", type_="submit", variant="ghost", size="sm"),
                "</form>",
            ]
        )
        rows.append(
            [
                esc(recipe.name),
                scope_badge(recipe.gender_path.value),
                esc(food_repo.MEAL_TYPE_LABELS.get(recipe.meal_type, recipe.meal_type)),
                f"{recipe.prep_minutes} דק׳",
                join([badge(food_repo.DIETARY_LABELS.get(tag, tag), tone="soft") for tag in recipe.dietary_tags]) or "—",
                badge("מאושר", tone="success") if recipe.approved else badge("ממתין", tone="warning"),
                toggle,
            ]
        )

    form = join(
        [
            '<form method="post" action="/admin/recipes" class="admin-form-grid" data-guard>',
            csrf_input(request.csrf_token),
            text_input("name", label="שם המתכון", required=True),
            textarea("description", label="תיאור", rows=2),
            '<div class="grid grid-2">',
            select("meal_type", food_repo.MEAL_TYPES, label="סוג ארוחה", value="lunch"),
            select("gender_path", SCOPE_OPTIONS, label="מסלול", value="all"),
            "</div>",
            textarea("ingredients", label="מרכיבים", rows=4, hint="שורה לכל מרכיב, בפורמט: שם | כמות | יחידה"),
            textarea("instructions", label="אופן ההכנה", rows=4, hint="שורה לכל שלב"),
            '<div class="grid grid-2">',
            text_input("prep_minutes", label="זמן הכנה (דקות)", type_="number", value="15"),
            text_input("dietary_tags", label="תגיות תזונה", hint="vegetarian, vegan, gluten_free…"),
            "</div>",
            text_input("allergens", label="אלרגנים", hint="nuts, dairy, gluten…"),
            f'<div class="row">{checkbox("approved", "מאושר לשימוש במנוע ההתאמה")}</div>',
            button("יצירת מתכון", type_="submit", variant="primary"),
            "</form>",
        ]
    )

    body = join(
        [
            '<div class="stack-lg">',
            content_tabs("recipes"),
            alert("רק מתכונים מאושרים נכנסים לתפריטים שהמערכת בונה למשתמשים.", tone="info"),
            table(["שם", "מסלול", "ארוחה", "הכנה", "תגיות", "סטטוס", ""], rows, empty_message="אין עדיין מתכונים"),
            card(card_header("מתכון חדש", icon_name="meal") + form),
            "</div>",
        ]
    )
    return html(admin_layout(body, title="מתכונים", context=ctx, active="programs", csrf_token=request.csrf_token))


def recipe_create(request: Request) -> Response:
    ctx = require_admin(request)
    form = request.form()
    name = _one(form, "name")[:160]
    if not name:
        return flash_redirect("/admin/programs?tab=recipes", "צריך שם למתכון", tone="error")

    ingredients = []
    for line in _one(form, "ingredients").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if parts and parts[0]:
            ingredients.append(
                {"name": parts[0], "amount": parts[1] if len(parts) > 1 else "", "unit": parts[2] if len(parts) > 2 else ""}
            )
    instructions = [line.strip() for line in _one(form, "instructions").splitlines() if line.strip()]
    scope = ContentScope.parse(_one(form, "gender_path", "all")) or ContentScope.ALL
    try:
        prep = max(1, min(600, int(_one(form, "prep_minutes", "15") or 15)))
    except ValueError:
        prep = 15

    recipe_id = food_repo.create_recipe(
        name=name,
        description=_one(form, "description")[:1000],
        ingredients=ingredients,
        instructions=instructions,
        meal_type=_one(form, "meal_type", "lunch"),
        gender_path=scope.value,
        dietary_tags=[tag.strip() for tag in _one(form, "dietary_tags").split(",") if tag.strip()],
        allergens=[tag.strip() for tag in _one(form, "allergens").split(",") if tag.strip()],
        prep_minutes=prep,
        approved=bool(form.get("approved")),
    )
    insights.record_audit(ctx.user.id, "recipe_created", entity_type="recipe", entity_id=str(recipe_id), ip_address=request.remote_addr)
    return flash_redirect("/admin/programs?tab=recipes", "המתכון נוצר")


def recipe_approve(request: Request) -> Response:
    """Approval is the gate the personalisation engine reads (27)."""
    ctx = require_admin(request)
    recipe_id = request.int_param("recipe_id")
    approved = str(request.data().get("approved", "1")) == "1"
    food_repo.update_recipe(recipe_id, approved=1 if approved else 0)
    insights.record_audit(
        ctx.user.id, "recipe_approval_changed", entity_type="recipe", entity_id=str(recipe_id),
        details={"approved": approved}, ip_address=request.remote_addr,
    )
    return flash_redirect("/admin/programs?tab=recipes", "האישור עודכן")


def register(router: Router) -> None:
    router.get("/admin/videos", videos_page)
    router.post("/admin/videos", video_create)
    router.get("/admin/videos/<int:video_id>/edit", video_edit)
    router.post("/admin/videos/<int:video_id>", video_update)
    router.post("/admin/videos/<int:video_id>/delete", video_delete)
    router.get("/admin/programs", programs_page)
    router.post("/admin/programs", program_create)
    router.get("/admin/programs/<int:program_id>", program_detail)
    router.post("/admin/recipes", recipe_create)
    router.post("/admin/recipes/<int:recipe_id>/approve", recipe_approve)
