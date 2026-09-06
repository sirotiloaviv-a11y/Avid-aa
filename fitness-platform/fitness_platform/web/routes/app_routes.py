"""The member product area (12, 13, 14, 15, 16, 17, 20, 21).

``/women/...`` and ``/men/...`` are the same handlers. The theme, the coach and
every row of content come from the session's path, and ``require_active`` is the
gate every one of them passes through. Writing the two areas as one
implementation is what keeps them from drifting apart; keeping the path out of
the handler arguments is what keeps them from leaking into each other.
"""

from __future__ import annotations

from datetime import date, datetime

from ...core.errors import NotFound
from ...core.request import Request
from ...core.response import Response, html, redirect
from ...core.router import Router
from ...db.repositories import content as content_repo, food as food_repo, insights, users as users_repo
from ...domain.gender import GenderPath
from ...domain.models import AuthContext, Video
from ...services import analytics, meal_service, program_service
from ...services.ai import coach as coach_service
from ...services.authorization import (
    require_active_subscription,
    require_content_access,
    require_owner,
    require_path,
)
from ..support import flash_redirect
from ..ui.charts import line_chart, week_strip
from ..ui.components import (
    alert,
    badge,
    button,
    card,
    card_header,
    checkbox,
    csrf_input,
    empty_state,
    filter_chip,
    media,
    play_overlay,
    program_card,
    progress_bar,
    progress_ring,
    section_header,
    stat_card,
    video_card,
)
from ..ui.icons import icon
from ..ui.layouts import app_layout
from ..ui.primitives import esc, join

GREETINGS = ((5, "בוקר טוב"), (12, "צהריים טובים"), (17, "אחר צהריים טובים"), (21, "ערב טוב"))


def _greeting() -> str:
    hour = datetime.now().hour
    label = "לילה טוב"
    for threshold, text in GREETINGS:
        if hour >= threshold:
            label = text
    return label


def _base(request: Request) -> tuple[AuthContext, GenderPath, str]:
    segment = request.param("segment")
    ctx = require_active_subscription(request, segment)
    assert ctx.user.gender_path is not None
    return ctx, ctx.user.gender_path, segment


def _base_no_subscription(request: Request) -> tuple[AuthContext, GenderPath, str]:
    """Settings and billing screens need the path guard but not an active
    subscription — otherwise a lapsed member could not reach the page that lets
    them resubscribe or delete their account."""
    segment = request.param("segment")
    ctx = require_path(request, segment)
    assert ctx.user.gender_path is not None
    return ctx, ctx.user.gender_path, segment


def _feminine(path: GenderPath, feminine: str, masculine: str) -> str:
    return feminine if path is GenderPath.FEMALE else masculine


def _video_href(segment: str, video_id: int) -> str:
    return f"/{segment}/workouts/{video_id}"


# ------------------------------------------------------------- dashboard ----
def dashboard(request: Request) -> Response:
    ctx, path, segment = _base(request)
    profile = ctx.profile
    workout = program_service.todays_workout(ctx)
    progress = program_service.weekly_progress(ctx)
    week = program_service.week_overview(ctx)
    recommended = program_service.recommended_videos(ctx, limit=3)
    recent = content_repo.recent_videos(ctx.user.id, path, limit=3)

    plan_id = meal_service.ensure_plan(ctx.user.id, profile, path)
    meals = meal_service.todays_meals(plan_id, path)
    shopping_list_id = food_repo.get_or_create_shopping_list(ctx.user.id, plan_id)
    shopping_items = food_repo.list_shopping_items(shopping_list_id)
    if not shopping_items and meals:
        # First visit of the week: derive the list from the plan rather than
        # showing an empty card the member has to go and populate by hand.
        meal_service.build_shopping_list(ctx.user.id, plan_id, path)
        shopping_items = food_repo.list_shopping_items(shopping_list_id)
    open_items = [item for item in shopping_items if not item["checked"]]

    start_label = _feminine(path, "התחילי אימון", "התחל אימון")
    hero = (
        f"""
        <section class="hero-workout">
          <div class="hero-workout-copy">
            <span class="hero-workout-eyebrow">האימון שלך היום</span>
            <h2>{esc(workout.title)}</h2>
            <div class="hero-workout-meta">
              <span>{icon("clock", size=15)} {workout.duration} דקות</span>
              <span>{icon("flame", size=15)} {esc(content_repo.DIFFICULTY_LABELS.get(workout.difficulty, workout.difficulty))}</span>
              <span>{icon("dumbbell", size=15)} {esc(content_repo.CATEGORY_LABELS.get(workout.category, workout.category))}</span>
            </div>
            {button(start_label, href=_video_href(segment, workout.id), variant="white", size="lg", icon_name="play")}
          </div>
          <a class="hero-workout-visual" href="{esc(_video_href(segment, workout.id))}" aria-label="{esc(workout.title)}">
            {media(seed=f"video-{workout.id}", label=workout.title, image_url=workout.thumbnail_url,
                   icon_name="dumbbell", overlay=play_overlay(f"{workout.duration} דק׳"))}
          </a>
        </section>
        """
        if workout
        else card(
            empty_state(
                "אנחנו מכינים עבורך את האימון הראשון",
                "ברגע שיעלה תוכן מתאים למסלול שלך, האימון היומי יופיע כאן אוטומטית.",
                icon_name="dumbbell",
            )
        )
    )

    meal_block = (
        join(
            [
                f"""
                <div class="today-meal">
                  {media(seed=f"recipe-{item['recipe'].id}", label=item['recipe'].name,
                         image_url=item['recipe'].image_url, icon_name="meal", ratio="1x1")}
                  <div class="meal-slot">
                    <div class="meal-slot-head"><span>{esc(food_repo.MEAL_TYPE_LABELS.get(item['meal_type'], item['meal_type']))}</span></div>
                    <a class="list-row-title" href="/{esc(segment)}/meals/{item['recipe'].id}">{esc(item['recipe'].name)}</a>
                    <p class="list-row-meta">{icon("clock", size=13)} {item['recipe'].prep_minutes} דקות הכנה</p>
                  </div>
                </div>
                """
                for item in meals[:2]
            ]
        )
        if meals
        else empty_state("התפריט בהכנה", "ברגע שיהיו מתכונים מאושרים שמתאימים להעדפות שלך, הם יופיעו כאן.", icon_name="meal")
    )

    shopping_block = (
        f"""
        <p class="muted small">{len(open_items)} פריטים פתוחים מתוך {len(shopping_items)}</p>
        <div class="list-rows">
          {join([f'<div class="list-row"><div class="list-row-main"><p class="list-row-title">{esc(item["name"])}</p><p class="list-row-meta">{esc(item["amount"])}</p></div></div>' for item in open_items[:3]])}
        </div>
        """
        if shopping_items
        else empty_state("הרשימה ריקה", "אחרי שייבנה התפריט השבועי, רשימת הקניות תיווצר ממנו.", icon_name="cart")
    )

    goals = profile.goals or []
    goal_labels = {
        "tone": "חיטוב וחיזוק", "strength": "כוח", "weight": "ירידה במשקל", "posture": "יציבה",
        "energy": "אנרגיה", "routine": "שגרה קבועה", "muscle": "עלייה במסה", "cut": "חיטוב",
        "endurance": "סיבולת", "mobility": "ניידות",
    }
    goals_block = (
        join(
            [
                f'<div class="goal-item"><span class="goal-check">{icon("check", size=13)}</span><span>{esc(goal_labels.get(goal, goal))}</span></div>'
                for goal in goals[:4]
            ]
        )
        if goals
        else '<p class="muted small">לא הוגדרו יעדים. אפשר לעדכן בהגדרות.</p>'
    )

    recommended_block = (
        f'<div class="grid grid-cards">{join([_video_card(segment, video) for video in recommended])}</div>'
        if recommended
        else card(empty_state("עוד רגע יהיה כאן תוכן", "אנחנו מוסיפים אימונים חדשים למסלול שלך.", icon_name="video"))
    )

    recent_block = (
        f'<div class="grid grid-cards">{join([_video_card(segment, video) for video in recent])}</div>'
        if recent
        else card(empty_state("עוד לא התחלת אימון", "האימון הראשון שתתחילו יופיע כאן.", icon_name="dumbbell"))
    )

    motivation = _feminine(
        path,
        ("את יכולה, עושה את זה!", "כל אימון שמסתיים הוא צעד קדימה. אנחנו כאן איתך."),
        ("אל תפסיק, אתה בדרך.", "העקביות היא מה שמייצר תוצאה. אימון אחר אימון."),
    )

    body = f"""
    <div class="stack-lg">
      {hero}

      <div class="grid grid-2">
        {card(card_header("תפריט היום", icon_name="meal", action=button("לתפריט המלא", href=f"/{segment}/meals", variant="ghost", size="sm", icon_end="arrow")) + f'<div class="today-card">{meal_block}</div>')}
        {card(card_header("רשימת קניות", icon_name="cart", action=button("לרשימה", href=f"/{segment}/shopping", variant="ghost", size="sm", icon_end="arrow")) + shopping_block)}
      </div>

      <div class="grid grid-3">
        {card(card_header("ההתקדמות שלך", icon_name="chart")
              + progress_ring(progress["percent"], caption="השבוע", sub_caption=f"{progress['done']}/{progress['target']} אימונים"))}
        {card(card_header("יעדים שבועיים", icon_name="target")
              + f'<div class="goal-list">{goals_block}</div>'
              + progress_bar(progress["percent"], label="יעד שבועי")
              + f'<div style="margin-top:var(--space-4)">{week_strip(week)}</div>')}
        f_motivation
      </div>

      <section>
        {section_header("האימונים הקרובים שלך", action=button("לכל האימונים", href=f"/{segment}/workouts", variant="ghost", size="sm", icon_end="arrow"))}
        {recommended_block}
      </section>

      <section>
        {section_header("המשך מאיפה שעצרת")}
        {recent_block}
      </section>

      {card(f'''
        <div class="row-between">
          <div class="row">
            <span class="card-header-icon">{icon("sparkles", size=18)}</span>
            <div>
              <h3 class="card-title">AI Coach</h3>
              <p class="card-subtitle">שאלות על האימון, החלפת תרגיל או ארוחה — בתוך התוכן שלך</p>
            </div>
          </div>
          {button("לדבר עם המאמן", href=f"/{segment}/coach", variant="primary", icon_end="arrow")}
        </div>
      ''')}
    </div>
    """
    body = body.replace(
        "f_motivation",
        f'''<div class="motivation">
              <span class="motivation-icon">{icon("flame", size=22)}</span>
              <h3>{esc(motivation[0])}</h3>
              <p>{esc(motivation[1])}</p>
              <p class="motivation-stat">{progress["total_completed"]} אימונים הושלמו עד היום</p>
            </div>''',
    )

    return html(
        app_layout(
            body,
            title="דשבורד",
            page_title=f"{_greeting()}, {esc(ctx.user.first_name)}!",
            subtitle=_feminine(path, "היום הוא היום שלך", "כוח, התמדה ותוצאות"),
            context=ctx,
            active="dashboard",
            csrf_token=request.csrf_token,
        )
    )


def _video_card(segment: str, video: Video) -> str:
    return video_card(
        video_id=video.id,
        title=video.title,
        duration=video.duration,
        difficulty_label=content_repo.DIFFICULTY_LABELS.get(video.difficulty, video.difficulty),
        category_label=content_repo.CATEGORY_LABELS.get(video.category, video.category),
        href=_video_href(segment, video.id),
        image_url=video.thumbnail_url,
        completed=video.completed,
        coach_name=video.coach_name,
    )


# -------------------------------------------------------------- workouts ----
def workouts(request: Request) -> Response:
    ctx, path, segment = _base(request)
    category = request.get("category")
    difficulty = request.get("difficulty")
    search = request.get("q")

    videos = content_repo.list_videos(
        path,
        category=category,
        difficulty=difficulty,
        search=search,
        user_id=ctx.user.id,
        limit=48,
    )

    chips = join(
        [filter_chip("הכול", f"/{segment}/workouts", not category)]
        + [
            filter_chip(label, f"/{segment}/workouts?category={key}", category == key)
            for key, label in content_repo.VIDEO_CATEGORIES
        ]
    )
    difficulty_chips = join(
        [filter_chip("כל הרמות", f"/{segment}/workouts", not difficulty)]
        + [
            filter_chip(label, f"/{segment}/workouts?difficulty={key}", difficulty == key)
            for key, label in content_repo.DIFFICULTIES
        ]
    )

    grid = (
        f'<div class="grid grid-cards">{join([_video_card(segment, video) for video in videos])}</div>'
        if videos
        else card(
            empty_state(
                "לא מצאנו אימונים מתאימים",
                "נסו לשנות את הסינון, או חזרו לכל האימונים.",
                icon_name="video",
                action=button("לכל האימונים", href=f"/{segment}/workouts", variant="secondary"),
            )
        )
    )

    body = f"""
    <div class="stack-lg">
      <form class="row" method="get" action="/{esc(segment)}/workouts">
        <div class="field grow">
          <input class="input" type="search" name="q" value="{esc(search)}" placeholder="חיפוש אימון…">
        </div>
        {button("חיפוש", type_="submit", variant="secondary")}
      </form>
      <div class="chips">{chips}</div>
      <div class="chips">{difficulty_chips}</div>
      {grid}
    </div>
    """
    return html(
        app_layout(
            body,
            title="האימונים שלי",
            subtitle=f"{len(videos)} אימונים זמינים במסלול שלך",
            context=ctx,
            active="workouts",
            csrf_token=request.csrf_token,
        )
    )


def workout_player(request: Request) -> Response:
    """The player (16). The video row is fetched *with* the path filter, so a
    member asking for the other path's id gets a 404, not a redirect."""
    ctx, path, segment = _base(request)
    video = content_repo.get_video(request.int_param("video_id"), path, user_id=ctx.user.id)
    if video is None:
        raise NotFound("האימון לא נמצא במסלול שלך.")
    require_content_access(ctx, video.gender_path)

    content_repo.mark_video_started(ctx.user.id, video.id)
    analytics.track(analytics.VIDEO_STARTED, user_id=ctx.user.id, gender_path=path.value, video_id=video.id)

    stage = (
        f'<video controls preload="metadata" poster="{esc(video.thumbnail_url)}"><source src="{esc(video.video_url)}"></video>'
        if video.video_url
        else f"""
        <div class="player-placeholder">
          <span class="empty-icon">{icon("video", size=26)}</span>
          <h3>הסרטון בהעלאה</h3>
          <p class="small">הקובץ עדיין לא הועלה למאגר. פרטי האימון והמעקב פעילים.</p>
        </div>
        """
    )

    equipment = ", ".join(video.equipment) if video.equipment else "ללא ציוד"
    complete_label = _feminine(path, "סיימתי את האימון", "סיימתי את האימון")
    body = f"""
    <div class="player-wrap">
      <div class="player-stage">{stage}</div>
      <div class="grid split">
        {card(f'''
          <div class="player-meta">
            {badge(content_repo.CATEGORY_LABELS.get(video.category, video.category), tone="soft")}
            {badge(content_repo.DIFFICULTY_LABELS.get(video.difficulty, video.difficulty), tone="outline")}
            {badge(f"{video.duration} דקות", tone="outline")}
            {badge("הושלם", tone="success", icon_name="check") if video.completed else ""}
          </div>
          <h2 style="margin-top:var(--space-3)">{esc(video.title)}</h2>
          <p class="muted" style="margin-top:var(--space-2)">{esc(video.description)}</p>
          <div class="player-actions" style="margin-top:var(--space-5)">
            <form method="post" action="/{esc(segment)}/workouts/{video.id}/complete" data-guard>
              {csrf_input(request.csrf_token)}
              {button(complete_label, type_="submit", variant="primary", icon_name="check")}
            </form>
            {button("לכל האימונים", href=f"/{segment}/workouts", variant="secondary")}
          </div>
        ''')}
        {card(card_header("פרטי האימון", icon_name="info") + f'''
          <div class="list-rows">
            <div class="list-row"><div class="list-row-main"><p class="list-row-meta">מאמן/ת</p><p class="list-row-title">{esc(video.coach_name or "צוות המערכת")}</p></div></div>
            <div class="list-row"><div class="list-row-main"><p class="list-row-meta">ציוד נדרש</p><p class="list-row-title">{esc(equipment)}</p></div></div>
            <div class="list-row"><div class="list-row-main"><p class="list-row-meta">משך</p><p class="list-row-title">{video.duration} דקות</p></div></div>
          </div>
        ''')}
      </div>
    </div>
    """
    return html(
        app_layout(
            body,
            title=video.title,
            subtitle="נצפה עכשיו",
            context=ctx,
            active="workouts",
            csrf_token=request.csrf_token,
        )
    )


def workout_complete(request: Request) -> Response:
    ctx, path, segment = _base(request)
    video = content_repo.get_video(request.int_param("video_id"), path)
    if video is None:
        raise NotFound()
    content_repo.mark_video_completed(ctx.user.id, video.id)
    analytics.track(analytics.VIDEO_COMPLETED, user_id=ctx.user.id, gender_path=path.value, video_id=video.id)
    return flash_redirect(f"/{segment}/dashboard", "כל הכבוד! האימון נרשם.")


# -------------------------------------------------------------- programs ----
def programs(request: Request) -> Response:
    ctx, path, segment = _base(request)
    active_id = content_repo.active_program_id(ctx.user.id)
    all_programs = content_repo.list_programs(path)
    cards = join(
        [
            program_card(
                program_id=program.id,
                name=program.name,
                description=program.description,
                weeks=program.duration_weeks,
                difficulty_label=content_repo.DIFFICULTY_LABELS.get(program.difficulty, program.difficulty),
                href=f"/{segment}/programs/{program.id}",
                active=program.id == active_id,
            )
            for program in all_programs
        ]
    )
    body = (
        f'<div class="grid grid-cards">{cards}</div>'
        if all_programs
        else card(empty_state("התוכניות בהכנה", "אנחנו בונים את התוכניות הראשונות למסלול שלך.", icon_name="program"))
    )
    return html(
        app_layout(body, title="תוכניות", subtitle="מסלולי אימון מובנים", context=ctx, active="programs", csrf_token=request.csrf_token)
    )


def program_detail(request: Request) -> Response:
    ctx, path, segment = _base(request)
    program = content_repo.get_program(request.int_param("program_id"), path)
    if program is None:
        raise NotFound("התוכנית לא נמצאה במסלול שלך.")
    require_content_access(ctx, program.gender_path)
    active_id = content_repo.active_program_id(ctx.user.id)

    days = join(
        [
            card(
                f"""
                <div class="row-between">
                  <div>
                    <p class="card-subtitle">יום {day.day_number}</p>
                    <h3 class="card-title">{esc(day.title or ("מנוחה" if day.is_rest else "אימון"))}</h3>
                    {f'<p class="muted small">{esc(day.focus)}</p>' if day.focus else ''}
                  </div>
                  {badge("מנוחה", tone="soft") if day.is_rest else badge(f"{len(day.videos)} סרטונים", tone="outline")}
                </div>
                {'<div class="list-rows" style="margin-top:var(--space-3)">' + join([
                    f'<a class="list-row" href="{_video_href(segment, video.id)}">'
                    f'<span class="goal-check">{icon("play", size=13)}</span>'
                    f'<div class="list-row-main"><p class="list-row-title">{esc(video.title)}</p>'
                    f'<p class="list-row-meta">{video.duration} דקות</p></div></a>'
                    for video in day.videos
                ]) + '</div>' if day.videos else ''}
                """,
                css_class="card-tight",
            )
            for day in program.days
        ]
    )

    start_form = f"""
    <form method="post" action="/{esc(segment)}/programs/{program.id}/start" data-guard>
      {csrf_input(request.csrf_token)}
      {button("התוכנית שלי" if program.id == active_id else "התחלת התוכנית", type_="submit",
              variant="secondary" if program.id == active_id else "primary", disabled=program.id == active_id)}
    </form>
    """

    body = f"""
    <div class="stack-lg">
      {card(f'''
        <div class="row-between">
          <div>
            <h2>{esc(program.name)}</h2>
            <p class="muted">{esc(program.description)}</p>
            <div class="row" style="margin-top:var(--space-3)">
              {badge(f"{program.duration_weeks} שבועות", tone="soft")}
              {badge(content_repo.DIFFICULTY_LABELS.get(program.difficulty, program.difficulty), tone="outline")}
            </div>
          </div>
          {start_form}
        </div>
      ''', css_class="card-pad-lg")}
      {section_header("מבנה התוכנית")}
      <div class="grid grid-2">{days}</div>
    </div>
    """
    return html(app_layout(body, title=program.name, context=ctx, active="programs", csrf_token=request.csrf_token))


def program_start(request: Request) -> Response:
    ctx, path, segment = _base(request)
    program = content_repo.get_program(request.int_param("program_id"), path, with_days=False)
    if program is None:
        raise NotFound()
    content_repo.assign_program(ctx.user.id, program.id)
    analytics.track(analytics.PROGRAM_STARTED, user_id=ctx.user.id, gender_path=path.value, program_id=program.id)
    return flash_redirect(f"/{segment}/programs/{program.id}", "התוכנית שלך עודכנה")




# ----------------------------------------------------------------- meals ----
def meals(request: Request) -> Response:
    ctx, path, segment = _base(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    grouped = meal_service.plan_days(plan_id, path)
    today = meal_service.today_index()

    day_cards = []
    for index in range(7):
        items = grouped.get(index, [])
        rows = join(
            [
                f"""
                <div class="list-row">
                  <div class="list-row-main">
                    <p class="list-row-meta">{esc(food_repo.MEAL_TYPE_LABELS.get(item['meal_type'], item['meal_type']))}</p>
                    <a class="list-row-title" href="/{esc(segment)}/meals/{item['recipe'].id}">{esc(item['recipe'].name)}</a>
                  </div>
                  <form method="post" action="/{esc(segment)}/meals/replace">
                    {csrf_input(request.csrf_token)}
                    <input type="hidden" name="day_index" value="{index}">
                    <input type="hidden" name="meal_type" value="{esc(item['meal_type'])}">
                    <input type="hidden" name="recipe_id" value="{item['recipe'].id}">
                    {button("החלפה", type_="submit", variant="ghost", size="sm")}
                  </form>
                </div>
                """
                for item in items
            ]
        )
        day_cards.append(
            card(
                f'<div class="row-between"><h3 class="card-title">{esc(program_service.HEBREW_DAYS[index])}</h3>'
                + (badge("היום", tone="brand") if index == today else "")
                + "</div>"
                + (f'<div class="list-rows" style="margin-top:var(--space-3)">{rows}</div>' if items
                   else '<p class="muted small" style="margin-top:var(--space-3)">אין ארוחות ליום הזה.</p>'),
                css_class="card-tight",
            )
        )

    actions = f"""
    <div class="row">
      <form method="post" action="/{esc(segment)}/meals/regenerate" data-guard>
        {csrf_input(request.csrf_token)}
        {button("בניית תפריט מחדש", type_="submit", variant="secondary")}
      </form>
      <form method="post" action="/{esc(segment)}/shopping/build" data-guard>
        {csrf_input(request.csrf_token)}
        {button("יצירת רשימת קניות", type_="submit", variant="primary", icon_name="cart")}
      </form>
    </div>
    """

    body = f"""
    <div class="stack-lg">
      {alert("התפריט נבנה ממתכונים מאושרים בלבד, בהתאם להעדפות ולרגישויות שסימנת. אין כאן ייעוץ תזונתי אישי.", tone="info")}
      {actions}
      <div class="grid grid-2">{join(day_cards)}</div>
    </div>
    """
    return html(
        app_layout(body, title="תפריט אוכל", subtitle="השבוע שלך", context=ctx, active="meals",
                   csrf_token=request.csrf_token)
    )


def meal_detail(request: Request) -> Response:
    ctx, path, segment = _base(request)
    recipe = food_repo.get_recipe(request.int_param("recipe_id"), path)
    if recipe is None:
        raise NotFound("המתכון לא נמצא במסלול שלך.")
    require_content_access(ctx, recipe.gender_path)
    analytics.track(analytics.RECIPE_VIEWED, user_id=ctx.user.id, gender_path=path.value, recipe_id=recipe.id)

    ingredients = join(
        [
            f'<div class="list-row"><div class="list-row-main"><p class="list-row-title">{esc(item.get("name", ""))}</p>'
            f'<p class="list-row-meta">{esc(str(item.get("amount", "")))} {esc(str(item.get("unit", "")))}</p></div></div>'
            for item in recipe.ingredients
        ]
    )
    steps = join(
        [
            f'<div class="list-row"><span class="goal-check">{index}</span>'
            f'<div class="list-row-main"><p class="list-row-title">{esc(step)}</p></div></div>'
            for index, step in enumerate(recipe.instructions, start=1)
        ]
    )
    tags = join([badge(food_repo.DIETARY_LABELS.get(tag, tag), tone="soft") for tag in recipe.dietary_tags])
    allergens = join([badge(food_repo.ALLERGEN_LABELS.get(tag, tag), tone="warning") for tag in recipe.allergens])

    body = f"""
    <div class="grid split">
      {card(f'''
        {media(seed=f"recipe-{recipe.id}", label=recipe.name, image_url=recipe.image_url, icon_name="meal", ratio="3x2")}
        <div class="row" style="margin-top:var(--space-4)">
          {badge(food_repo.MEAL_TYPE_LABELS.get(recipe.meal_type, recipe.meal_type), tone="outline")}
          {badge(f"{recipe.prep_minutes} דקות", tone="outline")}{tags}
        </div>
        <h2 style="margin-top:var(--space-3)">{esc(recipe.name)}</h2>
        <p class="muted">{esc(recipe.description)}</p>
        {f'<div class="row" style="margin-top:var(--space-3)"><span class="small muted">מכיל:</span>{allergens}</div>' if allergens else ''}
        <form method="post" action="/{esc(segment)}/shopping/add" style="margin-top:var(--space-5)">
          {csrf_input(request.csrf_token)}
          <input type="hidden" name="recipe_id" value="{recipe.id}">
          {button("הוספה לרשימת הקניות", type_="submit", variant="primary", icon_name="cart")}
        </form>
      ''')}
      <div class="stack">
        {card(card_header("מרכיבים", icon_name="leaf") + f'<div class="list-rows">{ingredients}</div>')}
        {card(card_header("אופן ההכנה", icon_name="info") + f'<div class="list-rows">{steps}</div>')}
      </div>
    </div>
    """
    return html(app_layout(body, title=recipe.name, context=ctx, active="meals", csrf_token=request.csrf_token))


def meal_replace(request: Request) -> Response:
    ctx, path, segment = _base(request)
    data = request.data()
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    require_owner(ctx, food_repo.meal_plan_owner(plan_id))
    try:
        day_index = int(data.get("day_index", 0))
        recipe_id = int(data.get("recipe_id", 0))
    except (TypeError, ValueError):
        raise NotFound()
    meal_type = str(data.get("meal_type", ""))
    replacement = meal_service.replace_meal(plan_id, ctx.profile, path, day_index, meal_type, recipe_id)
    if replacement is None:
        return flash_redirect(f"/{segment}/meals", "לא נמצאה חלופה מתאימה כרגע", tone="error")
    analytics.track(analytics.MEAL_REPLACED, user_id=ctx.user.id, gender_path=path.value)
    return flash_redirect(f"/{segment}/meals", f"הוחלף ל{replacement.name}")


def meal_regenerate(request: Request) -> Response:
    ctx, path, segment = _base(request)
    meal_service.generate_plan(ctx.user.id, ctx.profile, path)
    return flash_redirect(f"/{segment}/meals", "בנינו לך תפריט חדש")


# -------------------------------------------------------------- shopping ----
def shopping(request: Request) -> Response:
    ctx, path, segment = _base(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    list_id = food_repo.get_or_create_shopping_list(ctx.user.id, plan_id)
    grouped = meal_service.shopping_items_by_category(list_id)

    sections = []
    for key, label in food_repo.SHOPPING_CATEGORIES:
        items = grouped.get(key, [])
        if not items:
            continue
        rows = join(
            [
                f'''
                <label class="list-row{" is-checked" if item["checked"] else ""}">
                  <input type="checkbox" data-toggle-url="/api/shopping/items/{item["id"]}/toggle"
                         {"checked" if item["checked"] else ""}>
                  <div class="list-row-main">
                    <p class="list-row-title">{esc(item["name"])}</p>
                    <p class="list-row-meta">{esc(item["amount"])}</p>
                  </div>
                </label>
                '''
                for item in items
            ]
        )
        sections.append(card(card_header(label, icon_name="cart") + f'<div class="list-rows">{rows}</div>'))

    if not sections:
        sections = [
            card(
                empty_state(
                    "הרשימה עדיין ריקה",
                    "אפשר ליצור רשימה מהתפריט השבועי בלחיצה אחת.",
                    icon_name="cart",
                    action=f'''<form method="post" action="/{esc(segment)}/shopping/build" data-guard>
                        {csrf_input(request.csrf_token)}
                        {button("יצירה מהתפריט", type_="submit", variant="primary")}
                    </form>''',
                )
            )
        ]

    body = f"""
    <div class="stack-lg">
      <div class="row">
        <form method="post" action="/{esc(segment)}/shopping/build" data-guard>
          {csrf_input(request.csrf_token)}
          {button("רענון מהתפריט", type_="submit", variant="secondary")}
        </form>
        <form method="post" action="/{esc(segment)}/shopping/clear" data-guard>
          {csrf_input(request.csrf_token)}
          {button("ניקוי מה שסומן", type_="submit", variant="ghost")}
        </form>
      </div>
      <div class="grid grid-2">{join(sections)}</div>
    </div>
    """
    return html(
        app_layout(body, title="רשימת קניות", subtitle="לפי מחלקות בסופר", context=ctx, active="shopping",
                   csrf_token=request.csrf_token)
    )


def shopping_build(request: Request) -> Response:
    ctx, path, segment = _base(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    meal_service.build_shopping_list(ctx.user.id, plan_id, path)
    return flash_redirect(f"/{segment}/shopping", "הרשימה נבנתה מהתפריט השבועי")


def shopping_add_recipe(request: Request) -> Response:
    ctx, path, segment = _base(request)
    recipe = food_repo.get_recipe(int(request.data().get("recipe_id", 0) or 0), path)
    if recipe is None:
        raise NotFound()
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    list_id = food_repo.get_or_create_shopping_list(ctx.user.id, plan_id)
    for ingredient in recipe.ingredients or []:
        name = str(ingredient.get("name", "")).strip()
        if name:
            food_repo.add_shopping_item(
                list_id, name, f"{ingredient.get('amount', '')} {ingredient.get('unit', '')}".strip()
            )
    analytics.track(analytics.RECIPE_ADDED, user_id=ctx.user.id, gender_path=path.value, recipe_id=recipe.id)
    return flash_redirect(f"/{segment}/shopping", "המרכיבים נוספו לרשימה")


def shopping_clear(request: Request) -> Response:
    ctx, path, segment = _base(request)
    plan_id = meal_service.ensure_plan(ctx.user.id, ctx.profile, path)
    list_id = food_repo.get_or_create_shopping_list(ctx.user.id, plan_id)
    require_owner(ctx, food_repo.shopping_list_owner(list_id))
    food_repo.clear_checked_items(list_id)
    return flash_redirect(f"/{segment}/shopping", "הפריטים שסומנו הוסרו")


# -------------------------------------------------------------- progress ----
def progress(request: Request) -> Response:
    ctx, path, segment = _base(request)
    weekly = program_service.weekly_progress(ctx)
    entries = insights.list_progress_entries(ctx.user.id, limit=20)
    completions = content_repo.completions_by_day(ctx.user.id, days=14)

    labels = sorted(completions.keys())[-10:]
    chart = line_chart(
        [{"name": "אימונים שהושלמו", "values": [completions[day] for day in labels], "tone": "brand"}],
        [day[5:] for day in labels],
    ) if labels else '<div class="chart-empty">אחרי האימון הראשון יופיע כאן גרף התקדמות</div>'

    weight_values = [entry["weight_kg"] for entry in entries if entry.get("weight_kg")]
    weight_labels = [entry["entry_date"][5:] for entry in entries if entry.get("weight_kg")]
    weight_chart = (
        line_chart([{"name": "משקל", "values": weight_values, "tone": "brand"}], weight_labels)
        if len(weight_values) > 1
        else '<div class="chart-empty">עוד לא נרשמו מספיק מדידות</div>'
    )

    body = f"""
    <div class="stack-lg">
      <div class="grid grid-4">
        {stat_card("אימונים שהושלמו", str(weekly["total_completed"]), icon_name="check", caption="מאז ההצטרפות")}
        {stat_card("השבוע", f"{weekly['done']}/{weekly['target']}", icon_name="flame", caption="יעד שבועי")}
        {stat_card("אחוז השלמה", f"{weekly['percent']}%", icon_name="chart", caption="מהיעד השבועי")}
        {stat_card("מדידות משקל", str(len(weight_values)), icon_name="target", caption="נרשמו במעקב")}
      </div>
      <div class="grid split">
        {card(card_header("אימונים לאורך זמן", icon_name="chart") + chart)}
        {card(card_header("רישום מדידה", icon_name="target") + f'''
          <form method="post" action="/{esc(segment)}/progress" class="stack">
            {csrf_input(request.csrf_token)}
            <div class="field">
              <label class="field-label" for="weight_kg">משקל (ק״ג)</label>
              <input class="input" id="weight_kg" name="weight_kg" type="number" step="0.1" min="30" max="250" required>
            </div>
            <div class="field">
              <label class="field-label" for="note">הערה</label>
              <input class="input" id="note" name="note" type="text" placeholder="איך הרגשת השבוע?">
            </div>
            {button("שמירה", type_="submit", variant="primary", full_width=True)}
          </form>
        ''')}
      </div>
      {card(card_header("מגמת משקל", icon_name="chart") + weight_chart)}
    </div>
    """
    return html(
        app_layout(body, title="מעקב התקדמות", context=ctx, active="progress", csrf_token=request.csrf_token)
    )


def progress_submit(request: Request) -> Response:
    ctx, path, segment = _base(request)
    data = request.data()
    try:
        weight = float(str(data.get("weight_kg", "")).replace(",", "."))
    except ValueError:
        return flash_redirect(f"/{segment}/progress", "צריך להזין מספר", tone="error")
    if not 30 <= weight <= 250:
        return flash_redirect(f"/{segment}/progress", "המשקל שהוזן לא הגיוני", tone="error")
    insights.upsert_progress_entry(ctx.user.id, date.today().isoformat(), weight, str(data.get("note", "")))
    users_repo.update_profile(ctx.user.id, {"weight_kg": weight})
    return flash_redirect(f"/{segment}/progress", "המדידה נשמרה")


# ------------------------------------------------------------- community ----
def community(request: Request) -> Response:
    ctx, path, segment = _base(request)
    body = f"""
    <div class="stack-lg">
      {card(empty_state(
          "הקהילה נפתחת בקרוב",
          "אנחנו בונים מרחב סגור למסלול שלך — שיתוף התקדמות, שאלות למאמן/ת ואתגרים שבועיים. "
          "עד אז, ה‑AI Coach זמין לכל שאלה.",
          icon_name="community",
          action=button("לדבר עם AI Coach", href=f"/{segment}/coach", variant="primary", icon_end="arrow"),
      ))}
    </div>
    """
    return html(app_layout(body, title="קהילה", context=ctx, active="community", csrf_token=request.csrf_token))


# -------------------------------------------------------------- AI coach ----
def coach(request: Request) -> Response:
    ctx, path, segment = _base(request)
    messages = coach_service.history(ctx)
    bubbles = join(
        [
            f'''<div class="chat-msg chat-msg-{esc(message["role"])}">
                   <div class="chat-bubble">{esc(message["content"])}</div>
                 </div>'''
            for message in messages
        ]
    ) or f'''<div class="chat-msg chat-msg-assistant"><div class="chat-bubble">
        שלום {esc(ctx.user.first_name)}! אני כאן כדי לעזור לך למצוא את האימון הנכון, להחליף ארוחה
        או להבין איך משתמשים במערכת. במה אפשר לעזור?
      </div></div>'''

    chips = join(
        [
            f'<button class="chip" type="button" data-suggestion="{esc(text)}">{esc(text)}</button>'
            for text in coach_service.suggestions(path)
        ]
    )

    body = f"""
    <div class="coach-wrap">
      {card(f'''
        <div class="chat" id="chat" data-endpoint="/api/ai/coach">{bubbles}</div>
        <div class="chat-suggestions" style="margin-top:var(--space-3)">{chips}</div>
        <form class="chat-form" id="chat-form" style="margin-top:var(--space-3)">
          {csrf_input(request.csrf_token)}
          <div class="field">
            <label class="visually-hidden" for="chat-input">שאלה למאמן</label>
            <input class="input" id="chat-input" name="question" autocomplete="off"
                   placeholder="מה תרצו לשאול?" maxlength="800" required>
          </div>
          {button("שליחה", type_="submit", variant="primary")}
        </form>
        <p class="coach-disclaimer" style="margin-top:var(--space-3)">
          המאמן עונה מתוך התוכן של המסלול שלך בלבד ואינו נותן ייעוץ רפואי.
        </p>
      ''')}
    </div>
    """
    return html(
        app_layout(body, title="AI Coach", subtitle="עוזר אישי בתוך התוכן שלך", context=ctx,
                   active="coach", csrf_token=request.csrf_token, scripts=("coach.js",))
    )


# -------------------------------------------------------------- settings ----
def settings_page(request: Request) -> Response:
    ctx, path, segment = _base_no_subscription(request)
    profile = ctx.profile
    subscription = ctx.subscription

    subscription_block = (
        f'''
        <div class="list-rows">
          <div class="list-row"><div class="list-row-main">
            <p class="list-row-meta">מסלול</p>
            <p class="list-row-title">{esc(subscription.plan_code)}</p></div>
            {badge(subscription.status.label, tone="success" if subscription.is_active else "warning")}
          </div>
          <div class="list-row"><div class="list-row-main">
            <p class="list-row-meta">בתוקף עד</p>
            <p class="list-row-title">{esc((subscription.current_period_end or "")[:10] or "—")}</p></div>
          </div>
        </div>
        <form method="post" action="/{esc(segment)}/settings/cancel" style="margin-top:var(--space-4)" data-guard>
          {csrf_input(request.csrf_token)}
          {button("ביטול חידוש המנוי", type_="submit", variant="ghost")}
        </form>
        '''
        if subscription
        else empty_state("אין מנוי פעיל", "אפשר להצטרף בכל רגע.", icon_name="credit",
                         action=button("לבחירת מנוי", href="/subscribe", variant="primary"))
    )

    equipment_options = (
        ("none", "בלי ציוד"), ("mat", "מזרן"), ("dumbbells", "משקולות יד"),
        ("bands", "גומיות"), ("kettlebell", "קטלבל"), ("gym", "חדר כושר"),
    )
    equipment_boxes = join(
        [checkbox("equipment", label, value=key, checked=key in (profile.equipment or []))
         for key, label in equipment_options]
    )

    body = f"""
    <div class="grid split">
      <div class="stack">
        {card(card_header("הפרופיל שלי", icon_name="users") + f'''
          <form method="post" action="/{esc(segment)}/settings" class="stack">
            {csrf_input(request.csrf_token)}
            <div class="field">
              <label class="field-label" for="name">שם מלא</label>
              <input class="input" id="name" name="name" value="{esc(ctx.user.name)}" required>
            </div>
            <div class="grid grid-2">
              <div class="field">
                <label class="field-label" for="weekly_frequency">אימונים בשבוע</label>
                <input class="input" id="weekly_frequency" name="weekly_frequency" type="number" min="1" max="7"
                       value="{profile.weekly_frequency}">
              </div>
              <div class="field">
                <label class="field-label" for="session_minutes">דקות לאימון</label>
                <input class="input" id="session_minutes" name="session_minutes" type="number" min="10" max="120"
                       value="{profile.session_minutes}">
              </div>
            </div>
            <div class="field">
              <span class="field-label">ציוד זמין</span>
              <div class="row">{equipment_boxes}</div>
            </div>
            {button("שמירת שינויים", type_="submit", variant="primary")}
          </form>
        ''')}
        {card(card_header("שינוי סיסמה", icon_name="shield") + f'''
          <form method="post" action="/{esc(segment)}/settings/password" class="stack">
            {csrf_input(request.csrf_token)}
            <div class="field">
              <label class="field-label" for="current_password">סיסמה נוכחית</label>
              <input class="input" id="current_password" name="current_password" type="password" required
                     autocomplete="current-password">
            </div>
            <div class="field">
              <label class="field-label" for="new_password">סיסמה חדשה</label>
              <input class="input" id="new_password" name="new_password" type="password" required
                     autocomplete="new-password">
            </div>
            {button("עדכון סיסמה", type_="submit", variant="secondary")}
          </form>
        ''')}
      </div>
      <div class="stack">
        {card(card_header("המנוי שלי", icon_name="credit") + subscription_block)}
        {card(card_header("החשבון שלי", icon_name="info") + f'''
          <div class="list-rows">
            <div class="list-row"><div class="list-row-main">
              <p class="list-row-meta">אימייל</p><p class="list-row-title">{esc(ctx.user.email)}</p></div></div>
            <div class="list-row"><div class="list-row-main">
              <p class="list-row-meta">מסלול</p><p class="list-row-title">{esc(path.label)}</p></div></div>
          </div>
          <p class="admin-note" style="margin-top:var(--space-3)">
            המסלול נקבע בהרשמה ואינו ניתן לשינוי עצמי. לשינוי יש לפנות לתמיכה.
          </p>
          <form method="post" action="/{esc(segment)}/settings/delete" style="margin-top:var(--space-4)"
                onsubmit="return confirm('למחוק את החשבון? הפעולה אינה הפיכה.');">
            {csrf_input(request.csrf_token)}
            {button("מחיקת החשבון", type_="submit", variant="danger")}
          </form>
        ''')}
      </div>
    </div>
    """
    return html(app_layout(body, title="הגדרות", context=ctx, active="settings", csrf_token=request.csrf_token))


def settings_save(request: Request) -> Response:
    ctx, path, segment = _base_no_subscription(request)
    form = request.form()
    name = (form.get("name", [""])[0] or "").strip()
    if len(name) >= 2:
        users_repo.update_profile_name(ctx.user.id, name)
    updates: dict = {"equipment": form.get("equipment", [])}
    for key, low, high in (("weekly_frequency", 1, 7), ("session_minutes", 10, 120)):
        raw = form.get(key, [""])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        updates[key] = max(low, min(high, value))
    users_repo.update_profile(ctx.user.id, updates)
    return flash_redirect(f"/{segment}/settings", "הפרטים עודכנו")


def settings_password(request: Request) -> Response:
    ctx, path, segment = _base_no_subscription(request)
    from ...core.errors import ValidationError
    from ...services import auth as auth_service

    data = request.data()
    try:
        auth_service.change_password(
            ctx.user, str(data.get("current_password", "")), str(data.get("new_password", ""))
        )
    except ValidationError as error:
        message = next(iter(error.errors.values()), error.message)
        return flash_redirect(f"/{segment}/settings", message, tone="error")
    return flash_redirect("/login", "הסיסמה עודכנה. אפשר להתחבר מחדש.")


def settings_cancel(request: Request) -> Response:
    ctx, path, segment = _base_no_subscription(request)
    from ...services.payments import billing_service

    billing_service.cancel_subscription(ctx.user)
    return flash_redirect(f"/{segment}/settings", "המנוי יבוטל בסוף התקופה ששולמה")


def settings_delete(request: Request) -> Response:
    """Account deletion (47)."""
    ctx, _, _ = _base_no_subscription(request)
    users_repo.delete_account(ctx.user.id)
    insights.record_audit(ctx.user.id, "account_deleted", entity_type="user", entity_id=str(ctx.user.id))
    from ...services.auth import SESSION_COOKIE

    response = flash_redirect("/", "החשבון נמחק. תודה שהיית איתנו.")
    response.delete_cookie(SESSION_COOKIE)
    return response


def register(router: Router) -> None:
    router.get("/<slug:segment>/dashboard", dashboard)
    router.get("/<slug:segment>/workouts", workouts)
    router.get("/<slug:segment>/workouts/<int:video_id>", workout_player)
    router.post("/<slug:segment>/workouts/<int:video_id>/complete", workout_complete)
    router.get("/<slug:segment>/programs", programs)
    router.get("/<slug:segment>/programs/<int:program_id>", program_detail)
    router.post("/<slug:segment>/programs/<int:program_id>/start", program_start)
    router.get("/<slug:segment>/meals", meals)
    router.get("/<slug:segment>/meals/<int:recipe_id>", meal_detail)
    router.post("/<slug:segment>/meals/replace", meal_replace)
    router.post("/<slug:segment>/meals/regenerate", meal_regenerate)
    router.get("/<slug:segment>/shopping", shopping)
    router.post("/<slug:segment>/shopping/build", shopping_build)
    router.post("/<slug:segment>/shopping/add", shopping_add_recipe)
    router.post("/<slug:segment>/shopping/clear", shopping_clear)
    router.get("/<slug:segment>/progress", progress)
    router.post("/<slug:segment>/progress", progress_submit)
    router.get("/<slug:segment>/community", community)
    router.get("/<slug:segment>/coach", coach)
    router.get("/<slug:segment>/settings", settings_page)
    router.post("/<slug:segment>/settings", settings_save)
    router.post("/<slug:segment>/settings/password", settings_password)
    router.post("/<slug:segment>/settings/cancel", settings_cancel)
    router.post("/<slug:segment>/settings/delete", settings_delete)
