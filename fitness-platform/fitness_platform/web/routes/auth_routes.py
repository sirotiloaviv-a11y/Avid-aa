"""Sign-up, sign-in, sign-out (3, 11).

Flow note: the account is created straight after the path is chosen, before the
questionnaire. The spec sketches account creation after payment; doing it first
is what makes "come back later and continue where you left off" real — the
answers live against a user row on the server rather than in a cookie, so the
member can switch device mid-questionnaire. Payment still gates every piece of
member content; an account without an active subscription can reach the
questionnaire, the preview and the pricing page and nothing else.
"""

from __future__ import annotations

from ...core.errors import AppError, RateLimited, Unauthorized, ValidationError
from ...core.request import Request
from ...core.response import Response, html, redirect
from ...core.router import Router
from ...domain.gender import GenderPath
from ...services import analytics, auth
from ...services.auth import SESSION_COOKIE
from ...services.authorization import context
from ...config import get_settings
from ..support import flash_redirect, home_for, safe_next
from ..ui.components import alert, button, card, csrf_input, text_input
from ..ui.icons import icon
from ..ui.layouts import public_layout
from ..ui.primitives import esc


def _auth_shell(
    *,
    title: str,
    subtitle: str,
    form: str,
    footer: str,
    theme: str = "theme-neutral",
    context_obj=None,
) -> str:
    body = f"""
    <div class="container narrow auth-wrap">
      {card(f'''
        <div class="auth-head">
          <span class="ready-badge" style="width:56px;height:56px">{icon("logo", size=26)}</span>
          <h1>{esc(title)}</h1>
          <p class="muted">{esc(subtitle)}</p>
        </div>
        {form}
        <p class="auth-foot">{footer}</p>
      ''', css_class="auth-card")}
    </div>
    """
    return public_layout(body, title=title, theme=theme, show_nav=False, context=context_obj)


def signup_form(request: Request, segment: str = "", errors: dict | None = None, values: dict | None = None) -> Response:
    path = GenderPath.from_url_segment(segment or request.param("segment", ""))
    if path is None:
        return redirect("/start")
    errors = errors or {}
    values = values or {}
    label = "מסלול נשים" if path is GenderPath.FEMALE else "מסלול גברים"
    form = f"""
    <form method="post" action="/start/{esc(path.url_segment)}" class="stack" data-guard>
      {csrf_input(request.csrf_token)}
      <input type="hidden" name="gender_path" value="{esc(path.value)}">
      {alert(f"נבחר {label}. אחרי ההרשמה נעבור לשאלון קצר.", tone="info")}
      {text_input("name", label="שם מלא", value=values.get("name", ""), required=True,
                  error=errors.get("name", ""), autocomplete="name")}
      {text_input("email", label="אימייל", type_="email", value=values.get("email", ""), required=True,
                  error=errors.get("email", ""), autocomplete="email")}
      {text_input("password", label="סיסמה", type_="password", required=True,
                  error=errors.get("password", ""), hint="לפחות 8 תווים, עדיף שילוב של אותיות ומספרים",
                  autocomplete="new-password")}
      {button("יוצרים חשבון וממשיכים", type_="submit", variant="primary", size="lg", full_width=True, icon_end="arrow")}
    </form>
    """
    footer = 'כבר יש לך חשבון? <a href="/login">להתחברות</a>'
    return html(
        _auth_shell(
            title="פותחים חשבון",
            subtitle="נשמור את ההתקדמות שלך כדי שתוכל/י להמשיך מתי שנוח",
            form=form,
            footer=footer,
            theme=path.theme,
        )
    )


def signup_submit(request: Request) -> Response:
    segment = request.param("segment", "")
    path = GenderPath.from_url_segment(segment)
    if path is None:
        return redirect("/start")

    data = request.data()
    email = str(data.get("email", ""))
    password = str(data.get("password", ""))
    name = str(data.get("name", ""))

    # The path comes from the URL, is validated against the enum, and is written
    # once at creation. Nothing later in the product reads it from a request.
    try:
        user = auth.register(email, password, name, path)
    except ValidationError as error:
        return signup_form(request, segment, error.errors, {"email": email, "name": name})
    except AppError as error:
        return signup_form(request, segment, {"email": error.message}, {"email": email, "name": name})

    analytics.track(analytics.GENDER_SELECTED, user_id=user.id, gender_path=path.value)
    session = auth.start_session(
        user, user_agent=request.headers.get("user-agent", ""), ip_address=request.remote_addr
    )
    response = redirect("/onboarding")
    _set_session_cookie(response, session.session_id)
    return response


def login_form(request: Request, error: str = "", email: str = "") -> Response:
    next_url = safe_next(request, "")
    form = f"""
    <form method="post" action="/login" class="stack" data-guard>
      {csrf_input(request.csrf_token)}
      {f'<input type="hidden" name="next" value="{esc(next_url)}">' if next_url else ''}
      {alert(error, tone="danger") if error else ''}
      {text_input("email", label="אימייל", type_="email", value=email, required=True, autocomplete="email")}
      {text_input("password", label="סיסמה", type_="password", required=True, autocomplete="current-password")}
      {button("התחברות", type_="submit", variant="primary", size="lg", full_width=True)}
    </form>
    """
    footer = 'עוד אין לך חשבון? <a href="/start">להרשמה</a>'
    return html(
        _auth_shell(
            title="ברוכים השבים",
            subtitle="נמשיך בדיוק מאיפה שעצרת",
            form=form,
            footer=footer,
        )
    )


def login_submit(request: Request) -> Response:
    data = request.data()
    email = str(data.get("email", ""))
    password = str(data.get("password", ""))
    try:
        user = auth.authenticate(email, password, ip_address=request.remote_addr)
    except (Unauthorized, RateLimited) as error:
        return login_form(request, error.message, email)

    session = auth.start_session(
        user, user_agent=request.headers.get("user-agent", ""), ip_address=request.remote_addr
    )
    ctx = auth.load_context(session.session_id)
    destination = safe_next(request, "") or home_for(ctx)
    response = redirect(destination)
    _set_session_cookie(response, session.session_id)
    return response


def logout(request: Request) -> Response:
    auth.end_session(request.session or "")
    response = flash_redirect("/", "התנתקת בהצלחה")
    response.delete_cookie(SESSION_COOKIE)
    return response


def _set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=settings.session_ttl_seconds,
        http_only=True,
        secure=settings.secure_cookies,
        same_site="Lax",
    )


def register(router: Router) -> None:
    router.get("/start/<slug:segment>", signup_form)
    router.post("/start/<slug:segment>", signup_submit)
    router.get("/login", login_form)
    router.post("/login", login_submit)
    router.post("/logout", logout)
