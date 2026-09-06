"""Page shells: public site, member app, admin console (12, 13, 22, 31, 32)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...config import get_settings
from ...domain.gender import GenderPath
from ...domain.models import AuthContext
from .components import avatar, icon_button, toast_host
from .icons import icon
from .primitives import esc, join


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    icon: str
    active: bool = False
    badge: str = ""


def brand_mark(*, href: str = "/", compact: bool = False) -> str:
    settings = get_settings()
    return f"""
    <a class="brand{' brand-compact' if compact else ''}" href="{esc(href)}">
      <span class="brand-mark">{icon("logo", size=22)}</span>
      <span class="brand-name">{esc(settings.brand_name)}</span>
    </a>
    """


def document(
    *,
    title: str,
    body: str,
    theme: str = "theme-neutral",
    body_class: str = "",
    scripts: Sequence[str] = (),
    description: str = "",
) -> str:
    settings = get_settings()
    page_title = f"{title} · {settings.brand_name}" if title else settings.brand_name
    script_tags = join([f'<script src="/static/js/{esc(name)}" defer></script>' for name in scripts])
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl" class="{esc(theme)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{esc(description or settings.brand_tagline)}">
<meta name="color-scheme" content="light">
<title>{esc(page_title)}</title>
<link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/layout.css">
<link rel="stylesheet" href="/static/css/pages.css">
</head>
<body class="{esc(body_class)}">
{body}
{toast_host()}
<script src="/static/js/app.js" defer></script>
{script_tags}
</body>
</html>"""


# ---------------------------------------------------------- public shell ----
_PUBLIC_NAV = (
    ("בית", "/"),
    ("תוכניות", "/#programs"),
    ("אימונים", "/#workouts"),
    ("תזונה", "/#nutrition"),
    ("מחירים", "/pricing"),
)


def public_layout(
    body: str,
    *,
    title: str,
    context: AuthContext | None = None,
    theme: str = "theme-neutral",
    scripts: Sequence[str] = (),
    description: str = "",
    show_nav: bool = True,
) -> str:
    settings = get_settings()
    links = join([f'<a href="{esc(href)}">{esc(label)}</a>' for label, href in _PUBLIC_NAV])
    if context:
        home = "/admin" if context.user.is_admin else (
            f"/{context.user.gender_path.url_segment}/dashboard" if context.user.gender_path else "/start"
        )
        account = f'<a class="btn btn-primary btn-sm" href="{esc(home)}"><span>לאזור האישי</span></a>'
    else:
        account = (
            '<a class="nav-link-plain" href="/login">התחברות</a>'
            '<a class="btn btn-primary btn-sm" href="/start"><span>מתחילים</span></a>'
        )

    header = f"""
    <header class="site-header">
      <div class="container site-header-inner">
        {brand_mark()}
        {f'<nav class="site-nav" aria-label="ניווט ראשי">{links}</nav>' if show_nav else ''}
        <div class="site-header-actions">{account}</div>
        <button class="btn-icon btn-icon-ghost site-menu-toggle" type="button" data-drawer-toggle="site-drawer" aria-label="תפריט">{icon("menu")}</button>
      </div>
      <div class="site-drawer" id="site-drawer" hidden>
        <nav aria-label="ניווט נייד">{links}</nav>
        <div class="site-drawer-actions">{account}</div>
      </div>
    </header>
    """

    footer = f"""
    <footer class="site-footer">
      <div class="container site-footer-inner">
        <div>
          {brand_mark()}
          <p class="site-footer-note">{esc(settings.brand_tagline)}</p>
        </div>
        <nav aria-label="קישורים">
          <a href="/pricing">מחירים</a>
          <a href="/login">התחברות</a>
          <a href="/legal/privacy">פרטיות</a>
          <a href="/legal/terms">תנאי שימוש</a>
        </nav>
        <p class="site-footer-legal">
          התוכן באתר הוא מידע כללי לאימון ולתזונה ואינו מהווה ייעוץ רפואי.
          <br>© {esc(settings.brand_name)}
        </p>
      </div>
    </footer>
    """
    return document(
        title=title,
        theme=theme,
        body=header + f'<main class="site-main">{body}</main>' + footer,
        body_class="body-public",
        scripts=scripts,
        description=description,
    )


# ------------------------------------------------------------- app shell ----
def member_nav(path: GenderPath, active: str) -> list[NavItem]:
    """The member sidebar (12, 13). Identical structure on both paths — only the
    theme and the content behind it differ."""
    base = f"/{path.url_segment}"
    items = (
        ("dashboard", "דשבורד", "", "dashboard"),
        ("workouts", "האימונים שלי", "/workouts", "dumbbell"),
        ("programs", "תוכניות", "/programs", "program"),
        ("meals", "תפריט אוכל", "/meals", "meal"),
        ("shopping", "רשימת קניות", "/shopping", "cart"),
        ("progress", "מעקב התקדמות", "/progress", "chart"),
        ("community", "קהילה", "/community", "community"),
        ("coach", "AI Coach", "/coach", "sparkles"),
        ("settings", "הגדרות", "/settings", "settings"),
    )
    return [
        NavItem(label=label, href=f"{base}{suffix}" if suffix else f"{base}/dashboard", icon=icon_name, active=key == active)
        for key, label, suffix, icon_name in items
    ]


def _sidebar(items: Sequence[NavItem], *, footer: str = "", subtitle: str = "") -> str:
    links = join(
        [
            f'<a class="side-link{" is-active" if item.active else ""}" href="{esc(item.href)}">'
            f'<span class="side-link-icon">{icon(item.icon)}</span>'
            f'<span class="side-link-label">{esc(item.label)}</span>'
            + (f'<span class="side-link-badge">{esc(item.badge)}</span>' if item.badge else "")
            + "</a>"
            for item in items
        ]
    )
    return f"""
    <aside class="sidebar" id="app-sidebar">
      <div class="sidebar-head">
        {brand_mark(href='/')}
        {f'<p class="sidebar-subtitle">{esc(subtitle)}</p>' if subtitle else ''}
        <button class="btn-icon btn-icon-ghost sidebar-close" type="button" data-drawer-toggle="app-sidebar" aria-label="סגירה">{icon("close", size=18)}</button>
      </div>
      <nav class="sidebar-nav" aria-label="ניווט ראשי">{links}</nav>
      <div class="sidebar-foot">{footer}</div>
    </aside>
    """


def _topbar(*, title: str, subtitle: str = "", context: AuthContext | None, actions: str = "") -> str:
    user_block = ""
    if context:
        name = context.user.name or context.user.email
        user_block = f"""
        <a class="topbar-user" href="{esc('/admin/settings' if context.user.is_admin else f'/{context.user.gender_path.url_segment}/settings' if context.user.gender_path else '/start')}">
          <span class="topbar-user-name">{esc(name)}</span>
          {avatar(name, size='sm')}
        </a>
        """
    return f"""
    <header class="topbar">
      <button class="btn-icon btn-icon-ghost topbar-menu" type="button" data-drawer-toggle="app-sidebar" aria-label="תפריט">{icon("menu")}</button>
      <div class="topbar-titles">
        <h1 class="topbar-title">{esc(title)}</h1>
        {f'<p class="topbar-subtitle">{esc(subtitle)}</p>' if subtitle else ''}
      </div>
      <div class="topbar-actions">
        {actions}
        {icon_button("bell", "התראות", href="#notifications")}
        {user_block}
      </div>
    </header>
    """


def app_layout(
    body: str,
    *,
    title: str,
    page_title: str = "",
    subtitle: str = "",
    context: AuthContext,
    active: str,
    csrf_token: str = "",
    scripts: Sequence[str] = (),
    actions: str = "",
) -> str:
    path = context.user.gender_path
    assert path is not None, "app_layout requires a user with a gender path"
    logout = f"""
    <form method="post" action="/logout" class="sidebar-logout">
      <input type="hidden" name="csrf_token" value="{esc(csrf_token)}">
      <button class="side-link side-link-quiet" type="submit">
        <span class="side-link-icon">{icon("logout")}</span>
        <span class="side-link-label">התנתקות</span>
      </button>
    </form>
    """
    shell = f"""
    <div class="app-shell">
      {_sidebar(member_nav(path, active), footer=logout)}
      <div class="app-main">
        {_topbar(title=page_title or title, subtitle=subtitle, context=context, actions=actions)}
        <main class="app-content">{body}</main>
      </div>
      <div class="drawer-backdrop" data-drawer-backdrop hidden></div>
    </div>
    """
    return document(
        title=title,
        theme=path.theme,
        body=shell,
        body_class="body-app",
        scripts=scripts,
    )


# ----------------------------------------------------------- admin shell ----
def admin_nav(active: str) -> list[NavItem]:
    items = (
        ("overview", "דשבורד ניהולי", "/admin", "dashboard"),
        ("users", "משתמשים", "/admin/users", "users"),
        ("billing", "מנויים ותשלומים", "/admin/billing", "credit"),
        ("videos", "תוכן וסרטונים", "/admin/videos", "video"),
        ("programs", "תוכניות ומתכונים", "/admin/programs", "program"),
        ("ai", "AI & אוטומציה", "/admin/ai", "sparkles"),
        ("analytics", "דוחות וסטטיסטיקות", "/admin/analytics", "chart"),
        ("settings", "הגדרות מערכת", "/admin/settings", "settings"),
    )
    return [NavItem(label=label, href=href, icon=icon_name, active=key == active) for key, label, href, icon_name in items]


def admin_layout(
    body: str,
    *,
    title: str,
    subtitle: str = "",
    context: AuthContext,
    active: str,
    csrf_token: str = "",
    scripts: Sequence[str] = (),
    actions: str = "",
) -> str:
    logout = f"""
    <form method="post" action="/logout" class="sidebar-logout">
      <input type="hidden" name="csrf_token" value="{esc(csrf_token)}">
      <button class="side-link side-link-quiet" type="submit">
        <span class="side-link-icon">{icon("logout")}</span>
        <span class="side-link-label">התנתקות</span>
      </button>
    </form>
    """
    shell = f"""
    <div class="app-shell admin-shell">
      {_sidebar(admin_nav(active), footer=logout, subtitle="ניהול מערכת")}
      <div class="app-main">
        {_topbar(title=title, subtitle=subtitle, context=context, actions=actions)}
        <main class="app-content">{body}</main>
      </div>
      <div class="drawer-backdrop" data-drawer-backdrop hidden></div>
    </div>
    """
    return document(title=title, theme="theme-admin", body=shell, body_class="body-admin", scripts=scripts)
