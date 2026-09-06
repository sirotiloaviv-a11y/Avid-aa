"""Plan selection, checkout hand-off and the provider webhook (10, 45)."""

from __future__ import annotations

from ...core.errors import BadRequest, NotFound
from ...core.request import Request
from ...core.response import Response, html, redirect, text
from ...core.router import Router
from ...db.repositories import billing as billing_repo
from ...domain.subscription import PLANS, get_plan
from ...services.authorization import require_user
from ...services.payments import billing_service
from ...services.payments.factory import get_provider
from ..support import flash_redirect, home_for
from ..ui.components import alert, button, card, csrf_input, price_display
from ..ui.icons import icon
from ..ui.layouts import public_layout
from ..ui.primitives import esc, join


def subscribe(request: Request) -> Response:
    ctx = require_user(request)
    path = ctx.user.gender_path
    if path is None:
        return redirect("/start")
    if ctx.has_active_subscription:
        return redirect(home_for(ctx))

    cards = []
    for plan in PLANS:
        features = join(
            [
                f'<div class="plan-feature">{icon("check", size=16)}<span>{esc(item)}</span></div>'
                for item in plan.highlights
            ]
        )
        suffix = "לחודש" if plan.interval == "month" else "לשנה"
        cards.append(
            card(
                f"""
                {f'<span class="plan-badge">{esc(plan.badge)}</span>' if plan.badge else ''}
                <div>
                  <h3>{esc(plan.name)}</h3>
                  {price_display(plan.price_cents, suffix)}
                </div>
                <div class="plan-features">{features}</div>
                <form method="post" action="/subscribe" data-guard>
                  {csrf_input(request.csrf_token)}
                  <input type="hidden" name="plan" value="{esc(plan.code)}">
                  {button("ממשיכים לתשלום", type_="submit", variant="primary" if plan.badge else "secondary", full_width=True)}
                </form>
                """,
                css_class="plan-card" + (" is-featured" if plan.badge else ""),
            )
        )

    status_note = ""
    if ctx.subscription and ctx.subscription.status.value == "past_due":
        status_note = alert("התשלום האחרון לא עבר. אפשר לנסות שוב עם אמצעי תשלום אחר.", tone="warning")

    body = f"""
    <div class="container pricing">
      <div class="center stack">
        <h1>עוד צעד אחד לתוכנית שלך</h1>
        <p class="muted">בחרו מסלול מנוי כדי לפתוח את האימונים, התפריט וה‑AI Coach.</p>
      </div>
      {status_note}
      <div class="pricing-grid">{join(cards)}</div>
      <p class="pricing-note">התשלום מתבצע אצל ספק סליקה חיצוני. פרטי האשראי לא נשמרים אצלנו.</p>
    </div>
    """
    return html(public_layout(body, title="בחירת מנוי", theme=path.theme, show_nav=False, context=ctx))


def start_checkout(request: Request) -> Response:
    ctx = require_user(request)
    plan_code = str(request.data().get("plan", ""))
    _, session = billing_service.start_checkout(ctx.user, plan_code)
    return redirect(session.redirect_url)


def mock_checkout(request: Request) -> Response:
    """The development checkout screen (50).

    Labelled as a test screen and collecting nothing: there is no card field
    here, because a fake card form is exactly the kind of real-looking fake this
    codebase avoids.
    """
    ctx = require_user(request)
    provider = get_provider()
    if not provider.is_mock:
        raise NotFound()

    subscription_id = request.int_param("subscription_id")
    subscription = billing_repo.get_subscription(subscription_id)
    if subscription is None or subscription.user_id != ctx.user.id:
        raise NotFound()
    plan = get_plan(subscription.plan_code)
    if plan is None:
        raise BadRequest("מסלול לא מוכר.")

    body = f"""
    <div class="container narrow auth-wrap">
      {card(f'''
        <div class="auth-head">
          <span class="mode-flag">{icon("info", size=14)} סביבת פיתוח — סליקה מדומה</span>
          <h1>אישור תשלום</h1>
          <p class="muted">{esc(plan.name)} · {esc(str(price_display(plan.price_cents)))}</p>
        </div>
        {alert("זהו מסך בדיקה. לא נאסף כאן שום פרט תשלום, ולא מתבצע חיוב אמיתי. "
               "בפרודקשן המשתמש מועבר לדף הסליקה של ספק התשלומים.", tone="info")}
        <form method="post" action="/billing/checkout/{subscription.id}" class="stack" data-guard>
          {csrf_input(request.csrf_token)}
          <input type="hidden" name="outcome" value="success">
          {button("אישור תשלום מוצלח", type_="submit", variant="primary", size="lg", full_width=True)}
        </form>
        <form method="post" action="/billing/checkout/{subscription.id}" class="stack" style="margin-top:var(--space-3)">
          {csrf_input(request.csrf_token)}
          <input type="hidden" name="outcome" value="failure">
          {button("הדמיית תשלום שנכשל", type_="submit", variant="ghost", full_width=True)}
        </form>
      ''', css_class="auth-card")}
    </div>
    """
    path = ctx.user.gender_path
    return html(
        public_layout(body, title="תשלום", theme=path.theme if path else "theme-neutral", show_nav=False)
    )


def mock_checkout_submit(request: Request) -> Response:
    """Confirming the test checkout emits a signed webhook through the normal
    handler — the browser response never grants access by itself (45)."""
    ctx = require_user(request)
    provider = get_provider()
    if not provider.is_mock:
        raise NotFound()

    subscription_id = request.int_param("subscription_id")
    subscription = billing_repo.get_subscription(subscription_id)
    if subscription is None or subscription.user_id != ctx.user.id:
        raise NotFound()

    outcome = str(request.data().get("outcome", "success"))
    event_type = "payment.succeeded" if outcome == "success" else "payment.failed"
    body, headers = provider.build_event(
        event_type, subscription.provider_ref, subscription.amount_cents
    )
    billing_service.handle_webhook(headers, body)

    if event_type == "payment.failed":
        return flash_redirect("/subscribe", "התשלום לא עבר. אפשר לנסות שוב.", tone="error")
    return flash_redirect("/onboarding/done", "המנוי הופעל! ברוכים הבאים.")


def subscription_done(request: Request) -> Response:
    ctx = require_user(request)
    return redirect(home_for(ctx))


def payment_webhook(request: Request) -> Response:
    """Provider callback. No session, no CSRF — authenticity is the signature."""
    status = billing_service.handle_webhook(request.headers, request.body)
    return text(status)


def register(router: Router) -> None:
    router.get("/subscribe", subscribe)
    router.post("/subscribe", start_checkout)
    router.get("/billing/checkout/<int:subscription_id>", mock_checkout)
    router.post("/billing/checkout/<int:subscription_id>", mock_checkout_submit)
    router.get("/onboarding/done", subscription_done)
    router.post("/api/payments/webhook", payment_webhook)
