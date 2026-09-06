"""Landing page, path selection, pricing and legal pages (4, 10)."""

from __future__ import annotations

from ...core.request import Request
from ...core.response import Response, html
from ...core.router import Router
from ...config import get_settings
from ...domain.gender import GenderPath
from ...domain.subscription import PLANS
from ...services.authorization import context
from ..support import home_for
from ..ui.components import button, card, price_display, section_header
from ..ui.icons import icon
from ..ui.layouts import public_layout
from ..ui.primitives import esc, join

_FEATURES = (
    ("dumbbell", "אימונים מותאמים", "כל אימון נבחר לפי הרמה, הציוד והזמן שיש לך — לא תוכנית גנרית."),
    ("meal", "תפריט שבנוי סביבך", "תפריט שבועי ממתכונים מאושרים, עם התחשבות בהעדפות וברגישויות."),
    ("cart", "רשימת קניות אוטומטית", "התפריט הופך לרשימת קניות מסודרת לפי מחלקות בסופר."),
    ("chart", "מעקב שרואים", "רצף אימונים, התקדמות שבועית ויעדים — במקום אחד."),
    ("sparkles", "AI Coach זמין", "שאלות על האימון, החלפת תרגיל או ארוחה — בתוך התוכן שלנו בלבד."),
    ("shield", "מסלול אישי וסגור", "כל מסלול מקבל את התוכן שלו. אין ערבוב בין המסלולים."),
)


def _path_card(path: GenderPath) -> str:
    if path is GenderPath.FEMALE:
        title, glyph, tags = "אישה", "female", ("אימונים", "תזונה", "בריאות", "איזון")
        cta = "בחרי במסלול נשים"
        css = "path-female"
    else:
        title, glyph, tags = "גבר", "male", ("אימונים", "תזונה", "כוח", "ביצועים")
        cta = "בחר במסלול גברים"
        css = "path-male"

    tag_html = join([f"<span>{esc(tag)}</span>" for tag in tags])
    return f"""
    <a class="path-card {css}" href="/start/{esc(path.url_segment)}">
      <div class="path-card-visual">
        <span class="path-card-glyph">{icon(glyph, size=76)}</span>
      </div>
      <div class="path-card-body">
        <span class="path-card-icon">{icon(glyph, size=26)}</span>
        <h3 class="path-card-title">{esc(title)}</h3>
        <div class="path-card-list">{tag_html}</div>
        <div class="path-card-cta">
          {button(cta, variant="primary", size="lg", full_width=True, icon_end="arrow")}
        </div>
      </div>
    </a>
    """


def landing(request: Request) -> Response:
    settings = get_settings()
    ctx = context(request)

    features = join(
        [
            f"""
            <article class="feature">
              <span class="feature-icon">{icon(icon_name, size=22)}</span>
              <h3>{esc(title)}</h3>
              <p>{esc(text)}</p>
            </article>
            """
            for icon_name, title, text in _FEATURES
        ]
    )

    body = f"""
    <div class="container">
      <section class="hero">
        <span class="hero-eyebrow">{icon("sparkles", size=14)} תוכנית אישית תוך כמה דקות</span>
        <h1 class="hero-title">כושר שנבנה <span>בשבילך</span>.</h1>
        <p class="hero-sub">
          {esc(settings.brand_name)} בונה לך תוכנית אימונים ותפריט שבועי לפי הרמה, הזמן והציוד שלך —
          ומלווה אותך בכל שבוע עם תוכן מקצועי, מעקב ו‑AI Coach.
        </p>
        <div class="hero-actions">
          {button("מתחילים עכשיו", href="/start", variant="primary", size="lg", icon_end="arrow")}
          {button("לצפייה במחירים", href="/pricing", variant="secondary", size="lg")}
        </div>
        <div class="hero-stats">
          <div class="hero-stat"><strong>2</strong><span>מסלולים נפרדים</span></div>
          <div class="hero-stat"><strong>9</strong><span>קטגוריות אימון</span></div>
          <div class="hero-stat"><strong>7</strong><span>ימי תפריט בשבוע</span></div>
        </div>
      </section>

      <section class="choose" id="choose">
        <div class="choose-head">
          <h2>מי מתאמן איתנו?</h2>
          <p>בחרו את המסלול שלכם — כל מסלול הוא חוויה נפרדת, עם מאמן ותוכן משלו.</p>
        </div>
        <div class="choose-grid">
          {_path_card(GenderPath.MALE)}
          {_path_card(GenderPath.FEMALE)}
        </div>
        <p class="choose-note">אפשר לעבור על השאלון ולראות את התוכנית לפני שמשלמים.</p>
      </section>

      <section class="section-block" id="programs">
        {section_header("איך זה עובד", subtitle="ארבעה צעדים מהרשמה לאימון הראשון")}
        <div class="feature-grid">{features}</div>
      </section>

      <section class="section-block" id="nutrition">
        {card(f'''
          <div class="row-between">
            <div>
              <h2>לא בטוחים מה מתאים לכם?</h2>
              <p class="muted">ענו על השאלון הקצר וקבלו הצצה לתוכנית — בלי כרטיס אשראי.</p>
            </div>
            {button("לשאלון", href="/start", variant="primary", icon_end="arrow")}
          </div>
        ''', css_class="card-pad-lg")}
      </section>
    </div>
    """
    return html(public_layout(body, title="", context=ctx, description="פלטפורמת כושר ותזונה אישית"))


def start(request: Request) -> Response:
    """Path selection. A logged-in user who already has a path goes home (2)."""
    ctx = context(request)
    if ctx and ctx.user.gender_path:
        from ...core.response import redirect

        return redirect(home_for(ctx))

    body = f"""
    <div class="container">
      <section class="choose" style="margin-top:var(--space-7)">
        <div class="choose-head">
          <h2>מי מתאמן איתנו?</h2>
          <p>בחרו את המסלול שלכם ונתחיל להגדיר את התוכנית הכי טובה עבורכם.</p>
        </div>
        <div class="choose-grid">
          {_path_card(GenderPath.MALE)}
          {_path_card(GenderPath.FEMALE)}
        </div>
        <p class="choose-note">כבר יש לכם חשבון? <a href="/login">התחברות</a></p>
      </section>
    </div>
    """
    return html(public_layout(body, title="בחירת מסלול", context=ctx, show_nav=False))


def pricing(request: Request) -> Response:
    ctx = context(request)
    settings = get_settings()
    cards = []
    for plan in PLANS:
        features = join(
            [
                f'<div class="plan-feature">{icon("check", size=16)}<span>{esc(item)}</span></div>'
                for item in plan.highlights
            ]
        )
        suffix = "לחודש" if plan.interval == "month" else "לשנה"
        monthly = (
            f'<p class="muted small">שווה ערך ל{esc(f"₪{plan.monthly_equivalent_cents // 100}")} לחודש</p>'
            if plan.interval == "year"
            else ""
        )
        cards.append(
            card(
                f"""
                {f'<span class="plan-badge">{esc(plan.badge)}</span>' if plan.badge else ''}
                <div>
                  <h3>{esc(plan.name)}</h3>
                  {price_display(plan.price_cents, suffix)}
                  {monthly}
                </div>
                <div class="plan-features">{features}</div>
                {button("לבחירת המסלול", href="/start", variant="primary" if plan.badge else "secondary", full_width=True)}
                """,
                css_class="plan-card" + (" is-featured" if plan.badge else ""),
            )
        )

    body = f"""
    <div class="container pricing">
      <div class="center stack">
        <h1>מנוי אחד, כל התוכן של המסלול שלך</h1>
        <p class="muted">בלי התחייבות ארוכה. אפשר לבטל בכל שלב מתוך אזור ההגדרות.</p>
      </div>
      <div class="pricing-grid">{join(cards)}</div>
      <p class="pricing-note">
        המחירים כוללים מע״מ. החיוב מתבצע דרך ספק סליקה מאובטח — {esc(settings.brand_name)} לא שומרת פרטי אשראי.
      </p>
    </div>
    """
    return html(public_layout(body, title="מחירים", context=ctx))


def legal_privacy(request: Request) -> Response:
    body = _legal_page(
        "מדיניות פרטיות",
        [
            ("איזה מידע נאסף", "פרטי חשבון (שם, אימייל), תשובות השאלון, והתקדמות באימונים ובתפריט. אנחנו אוספים רק מה שנדרש כדי לבנות ולהציג את התוכנית."),
            ("איך משתמשים במידע", "המידע משמש להתאמת התוכן שמוצג לכם ולשיפור המוצר. אנחנו לא מוכרים מידע אישי."),
            ("פרטי תשלום", "פרטי כרטיס אשראי לא נשמרים אצלנו. הסליקה מתבצעת אצל ספק תשלומים חיצוני."),
            ("מחיקת חשבון", "אפשר למחוק את החשבון מתוך ההגדרות. המחיקה מסירה את הפרטים האישיים ואת תשובות השאלון."),
            ("יצירת קשר", "לשאלות בנושא פרטיות אפשר לפנות אלינו במייל התמיכה."),
        ],
    )
    return html(public_layout(body, title="מדיניות פרטיות", context=context(request)))


def legal_terms(request: Request) -> Response:
    body = _legal_page(
        "תנאי שימוש",
        [
            ("השירות", "הפלטפורמה מספקת תוכן אימונים ותזונה כללי, מותאם לפי העדפות שנמסרו בשאלון."),
            ("אינו ייעוץ רפואי", "התוכן אינו מהווה ייעוץ רפואי, אבחון או טיפול. לפני התחלת פעילות גופנית מומלץ להתייעץ עם גורם מקצועי מתאים."),
            ("מנוי וחיוב", "המנוי מתחדש בהתאם למסלול שנבחר וניתן לביטול בכל עת. הגישה נשמרת עד סוף התקופה ששולמה."),
            ("שימוש בתוכן", "התוכן מיועד לשימוש אישי בלבד ואין להפיץ או לשכפל אותו."),
        ],
    )
    return html(public_layout(body, title="תנאי שימוש", context=context(request)))


def _legal_page(title: str, sections: list[tuple[str, str]]) -> str:
    blocks = join(
        [
            f"<section class='stack-sm'><h2>{esc(heading)}</h2><p class='muted'>{esc(text)}</p></section>"
            for heading, text in sections
        ]
    )
    return f"""
    <div class="container narrow" style="padding-block:var(--space-8)">
      <h1>{esc(title)}</h1>
      <div class="stack-lg" style="margin-top:var(--space-6)">{blocks}</div>
    </div>
    """


def register(router: Router) -> None:
    router.get("/", landing)
    router.get("/start", start)
    router.get("/pricing", pricing)
    router.get("/legal/privacy", legal_privacy)
    router.get("/legal/terms", legal_terms)
