"""The multi-step questionnaire and the "your plan is ready" screen (7, 8, 9)."""

from __future__ import annotations

from ...core.request import Request
from ...core.response import Response, html, redirect
from ...core.router import Router
from ...domain.onboarding import Question
from ...services import onboarding_service, program_service
from ...services.authorization import require_user
from ...db.repositories import users as users_repo
from ..ui.components import (
    button,
    card,
    csrf_input,
    empty_state,
    option_card,
    progress_bar,
    text_input,
)
from ..ui.icons import icon
from ..ui.layouts import public_layout
from ..ui.primitives import esc, join


def _render_question(question: Question, answers: dict, errors: dict) -> str:
    value = answers.get(question.key)
    error = errors.get(question.key, "")

    if question.type in ("single", "multi"):
        selected = value if isinstance(value, list) else ([value] if value not in (None, "") else [])
        selected = [str(item) for item in selected]
        options = join(
            [
                option_card(
                    question.key,
                    option.value,
                    option.label,
                    hint=option.hint,
                    checked=option.value in selected,
                    multiple=question.type == "multi",
                )
                for option in question.options
            ]
        )
        control = f'<div class="option-grid">{options}</div>'
        error_html = f'<p class="field-error">{esc(error)}</p>' if error else ""
        help_html = f'<p class="question-help">{esc(question.help_text)}</p>' if question.help_text else ""
        return f"""
        <fieldset class="question">
          <legend class="question-label">{esc(question.label)}</legend>
          {help_html}
          {control}
          {error_html}
        </fieldset>
        """

    input_type = "number" if question.type == "number" else "text"
    raw_value = "" if value in (None, []) else (", ".join(value) if isinstance(value, list) else str(value))
    return f'<div class="question">{text_input(question.key, label=question.label, value=raw_value, type_=input_type, placeholder=question.placeholder, required=question.required, error=error, hint=question.help_text)}</div>'


def _render_step(request: Request, view: onboarding_service.StepView) -> Response:
    path = require_user(request).user.gender_path
    questions = join([_render_question(question, view.answers, view.errors) for question in view.step.questions])
    back = (
        button("חזרה", href=f"/onboarding/{view.index - 1}", variant="ghost")
        if view.index > 0
        else '<span class="muted small">אפשר לחזור אחורה בכל שלב</span>'
    )
    body = f"""
    <div class="container onboarding">
      {card(f'''
        <div class="steps-head">
          <div class="steps-meta">
            <span>שלב {view.index + 1} מתוך {view.total}</span>
            <span>{view.percent}%</span>
          </div>
          {progress_bar(view.percent)}
          <h1 class="step-title">{esc(view.step.title)}</h1>
          <p class="step-subtitle">{esc(view.step.subtitle)}</p>
        </div>
        <form method="post" action="/onboarding/{view.index}">
          {csrf_input(request.csrf_token)}
          {questions}
          <div class="onboarding-actions">
            {back}
            {button("שמירה והמשך" if not view.is_last else "סיום השאלון", type_="submit", variant="primary", size="lg", icon_end="arrow")}
          </div>
        </form>
      ''', css_class="onboarding-card")}
    </div>
    """
    return html(
        public_layout(
            body,
            title="שאלון התאמה",
            theme=path.theme if path else "theme-neutral",
            show_nav=False,
        )
    )


def onboarding_entry(request: Request) -> Response:
    ctx = require_user(request)
    if ctx.user.gender_path is None:
        return redirect("/start")
    if ctx.user.onboarding_completed:
        return redirect("/onboarding/ready")
    return redirect(f"/onboarding/{onboarding_service.resume_index(ctx.user)}")


def onboarding_step(request: Request) -> Response:
    ctx = require_user(request)
    if ctx.user.gender_path is None:
        return redirect("/start")
    index = request.int_param("index")
    view = onboarding_service.load_step(ctx.user, index)
    if view is None:
        return redirect("/onboarding")
    return _render_step(request, view)


def onboarding_submit(request: Request) -> Response:
    ctx = require_user(request)
    if ctx.user.gender_path is None:
        return redirect("/start")
    index = request.int_param("index")
    ok, view = onboarding_service.submit_step(ctx.user, index, request.form())
    if not ok:
        if view is None:
            return redirect("/onboarding")
        return _render_step(request, view)

    total = view.total if view else onboarding_service.load_step(ctx.user, 0).total
    if index + 1 >= total:
        onboarding_service.complete(ctx.user)
        return redirect("/onboarding/ready")
    return redirect(f"/onboarding/{index + 1}")


def onboarding_ready(request: Request) -> Response:
    """The plan preview (9). Nothing is charged here; the CTA leads to pricing."""
    ctx = require_user(request)
    path = ctx.user.gender_path
    if path is None:
        return redirect("/start")
    if not ctx.user.onboarding_completed:
        return redirect("/onboarding")

    profile = users_repo.get_profile(ctx.user.id)
    preview = program_service.build_preview(profile, path)

    if preview.program is None and not preview.sample_videos:
        summary = empty_state(
            "אנחנו מכינים עבורך את התוכנית הראשונה",
            "התוכן למסלול הזה נמצא בהכנה. ברגע שהוא יעלה, התוכנית שלך תיבנה אוטומטית לפי התשובות ששמרת.",
            icon_name="sparkles",
        )
    else:
        highlights = join(
            [
                f'<div class="plan-feature">{icon("check", size=16)}<span>{esc(text)}</span></div>'
                for text in (
                    f"{preview.weekly_sessions} אימונים בשבוע, {preview.session_minutes} דקות לאימון",
                    f"דגשים: {', '.join(preview.focus_labels) if preview.focus_labels else 'גוף מלא'}",
                    "תפריט שבועי ורשימת קניות שנבנים מהעדפות האוכל שלך",
                    "AI Coach שמכיר רק את התוכן של המסלול שלך",
                )
            ]
        )
        program_line = (
            f'<p class="muted">התוכנית שנבחרה: <strong>{esc(preview.program.name)}</strong> · '
            f'{preview.program.duration_weeks} שבועות</p>'
            if preview.program
            else '<p class="muted">בנינו לך מסלול אימונים אישי מתוך ספריית הסרטונים.</p>'
        )
        summary = f"""
        <div class="ready">
          <span class="ready-badge">{icon("check", size=30)}</span>
          <h1>התוכנית שלך מוכנה!</h1>
          <p class="muted">יצרנו עבורך מסלול אישי בהתאם לתשובות שלך.</p>
          {program_line}
          <div class="ready-summary">{highlights}</div>
          {button("המשך לבחירת מנוי", href="/subscribe", variant="primary", size="lg", icon_end="arrow")}
          <p class="small muted">אפשר לעדכן את התשובות בכל שלב מתוך ההגדרות.</p>
        </div>
        """

    body = f'<div class="container narrow onboarding">{card(summary, css_class="onboarding-card")}</div>'
    return html(public_layout(body, title="התוכנית שלך מוכנה", theme=path.theme, show_nav=False))


def register(router: Router) -> None:
    router.get("/onboarding", onboarding_entry)
    router.get("/onboarding/ready", onboarding_ready)
    router.get("/onboarding/<int:index>", onboarding_step)
    router.post("/onboarding/<int:index>", onboarding_submit)
