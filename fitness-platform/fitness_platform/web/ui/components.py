"""The shared component library (29).

Every screen is assembled from these. Nothing renders a raw ``<button>`` or a
bespoke card: when a control needs a new variant it grows here, once, and every
screen gets it.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .icons import icon
from .primitives import attrs, classes, esc, join, money

# --------------------------------------------------------------- buttons ----
def button(
    label: str,
    *,
    href: str = "",
    variant: str = "primary",
    size: str = "md",
    icon_name: str = "",
    icon_end: str = "",
    full_width: bool = False,
    type_: str = "button",
    disabled: bool = False,
    **extra: Any,
) -> str:
    css = classes("btn", f"btn-{variant}", f"btn-{size}", {"btn-block": full_width})
    inner = join(
        [
            icon(icon_name, size=18) if icon_name else "",
            f"<span>{esc(label)}</span>",
            icon(icon_end, size=18) if icon_end else "",
        ]
    )
    if href:
        return f'<a class="{css}" href="{esc(href)}"{attrs(extra)}>{inner}</a>'
    return (
        f'<button class="{css}" type="{esc(type_)}"'
        f'{attrs({"disabled": disabled})}{attrs(extra)}>{inner}</button>'
    )


def icon_button(icon_name: str, label: str, *, href: str = "", variant: str = "ghost", **extra: Any) -> str:
    css = classes("btn-icon", f"btn-icon-{variant}")
    inner = icon(icon_name, size=20)
    if href:
        return f'<a class="{css}" href="{esc(href)}" aria-label="{esc(label)}"{attrs(extra)}>{inner}</a>'
    return f'<button class="{css}" type="button" aria-label="{esc(label)}"{attrs(extra)}>{inner}</button>'


# ------------------------------------------------------------------ cards ---
def card(content: str, *, css_class: str = "", **extra: Any) -> str:
    return f'<section class="{classes("card", css_class)}"{attrs(extra)}>{content}</section>'


def card_header(title: str, *, subtitle: str = "", action: str = "", icon_name: str = "") -> str:
    left = join(
        [
            f'<span class="card-header-icon">{icon(icon_name, size=18)}</span>' if icon_name else "",
            f'<div><h3 class="card-title">{esc(title)}</h3>'
            + (f'<p class="card-subtitle">{esc(subtitle)}</p>' if subtitle else "")
            + "</div>",
        ]
    )
    action_html = f'<div class="card-header-action">{action}</div>' if action else ""
    return (
        '<header class="card-header">'
        f'<div class="card-header-main">{left}</div>'
        f"{action_html}"
        "</header>"
    )


def stat_card(
    label: str,
    value: str,
    *,
    icon_name: str = "chart",
    tone: str = "brand",
    delta: str = "",
    delta_direction: str = "up",
    caption: str = "",
) -> str:
    delta_html = ""
    if delta:
        delta_html = (
            f'<span class="stat-delta stat-delta-{esc(delta_direction)}">{esc(delta)}</span>'
        )
    return f"""
    <article class="stat-card tone-{esc(tone)}">
      <div class="stat-card-top">
        <span class="stat-icon">{icon(icon_name, size=20)}</span>
        <span class="stat-ghost-icon">{icon(icon_name, size=18)}</span>
      </div>
      <p class="stat-label">{esc(label)}</p>
      <p class="stat-value"><span class="ltr-num">{esc(value)}</span></p>
      <p class="stat-foot">{delta_html}{f'<span class="stat-caption">{esc(caption)}</span>' if caption else ''}</p>
    </article>
    """


def section_header(title: str, *, subtitle: str = "", action: str = "") -> str:
    return f"""
    <div class="section-header">
      <div>
        <h2 class="section-title">{esc(title)}</h2>
        {f'<p class="section-subtitle">{esc(subtitle)}</p>' if subtitle else ''}
      </div>
      {f'<div class="section-action">{action}</div>' if action else ''}
    </div>
    """


# ------------------------------------------------------------------ forms ---
def field_wrapper(label: str, control: str, *, name: str = "", error: str = "", hint: str = "") -> str:
    return f"""
    <div class="field{' field-invalid' if error else ''}">
      {f'<label class="field-label" for="{esc(name)}">{esc(label)}</label>' if label else ''}
      {control}
      {f'<p class="field-hint">{esc(hint)}</p>' if hint and not error else ''}
      {f'<p class="field-error">{esc(error)}</p>' if error else ''}
    </div>
    """


def text_input(
    name: str,
    *,
    label: str = "",
    value: str = "",
    type_: str = "text",
    placeholder: str = "",
    required: bool = False,
    error: str = "",
    hint: str = "",
    autocomplete: str = "",
    **extra: Any,
) -> str:
    control = (
        f'<input class="input" id="{esc(name)}" name="{esc(name)}" type="{esc(type_)}" '
        f'value="{esc(value)}" placeholder="{esc(placeholder)}"'
        f'{attrs({"required": required, "autocomplete": autocomplete or None})}{attrs(extra)}>'
    )
    return field_wrapper(label, control, name=name, error=error, hint=hint)


def textarea(name: str, *, label: str = "", value: str = "", rows: int = 4, placeholder: str = "", error: str = "", hint: str = "", **extra: Any) -> str:
    control = (
        f'<textarea class="input textarea" id="{esc(name)}" name="{esc(name)}" rows="{rows}" '
        f'placeholder="{esc(placeholder)}"{attrs(extra)}>{esc(value)}</textarea>'
    )
    return field_wrapper(label, control, name=name, error=error, hint=hint)


def select(
    name: str,
    options: Sequence[tuple[str, str]],
    *,
    label: str = "",
    value: str = "",
    placeholder: str = "",
    error: str = "",
    hint: str = "",
    **extra: Any,
) -> str:
    parts = [f'<option value="">{esc(placeholder)}</option>'] if placeholder else []
    for option_value, option_label in options:
        selected = " selected" if str(option_value) == str(value) else ""
        parts.append(f'<option value="{esc(option_value)}"{selected}>{esc(option_label)}</option>')
    control = (
        f'<div class="select-wrap"><select class="input select" id="{esc(name)}" name="{esc(name)}"'
        f'{attrs(extra)}>{join(parts)}</select></div>'
    )
    return field_wrapper(label, control, name=name, error=error, hint=hint)


def checkbox(name: str, label: str, *, value: str = "1", checked: bool = False, **extra: Any) -> str:
    return f"""
    <label class="choice choice-checkbox">
      <input type="checkbox" name="{esc(name)}" value="{esc(value)}"{attrs({"checked": checked})}{attrs(extra)}>
      <span class="choice-box">{icon("check", size=14)}</span>
      <span class="choice-label">{esc(label)}</span>
    </label>
    """


def radio(name: str, label: str, value: str, *, checked: bool = False, **extra: Any) -> str:
    return f"""
    <label class="choice choice-radio">
      <input type="radio" name="{esc(name)}" value="{esc(value)}"{attrs({"checked": checked})}{attrs(extra)}>
      <span class="choice-box"></span>
      <span class="choice-label">{esc(label)}</span>
    </label>
    """


def option_card(
    name: str,
    value: str,
    title: str,
    *,
    hint: str = "",
    checked: bool = False,
    multiple: bool = False,
    icon_name: str = "",
) -> str:
    input_type = "checkbox" if multiple else "radio"
    return f"""
    <label class="option-card">
      <input type="{input_type}" name="{esc(name)}" value="{esc(value)}"{attrs({"checked": checked})}>
      <span class="option-card-body">
        {f'<span class="option-card-icon">{icon(icon_name, size=20)}</span>' if icon_name else ''}
        <span class="option-card-text">
          <span class="option-card-title">{esc(title)}</span>
          {f'<span class="option-card-hint">{esc(hint)}</span>' if hint else ''}
        </span>
        <span class="option-card-mark">{icon("check", size=14)}</span>
      </span>
    </label>
    """


def csrf_input(token: str) -> str:
    return f'<input type="hidden" name="csrf_token" value="{esc(token)}">'


# ----------------------------------------------------------- feedback bits --
def badge(text: str, *, tone: str = "neutral", icon_name: str = "") -> str:
    return (
        f'<span class="badge badge-{esc(tone)}">'
        f'{icon(icon_name, size=14) if icon_name else ""}{esc(text)}</span>'
    )


def alert(message: str, *, tone: str = "info", title: str = "") -> str:
    icon_by_tone = {"info": "info", "success": "check", "warning": "info", "danger": "info"}
    return f"""
    <div class="alert alert-{esc(tone)}" role="status">
      <span class="alert-icon">{icon(icon_by_tone.get(tone, "info"), size=18)}</span>
      <div>
        {f'<strong>{esc(title)}</strong>' if title else ''}
        <p>{esc(message)}</p>
      </div>
    </div>
    """


def toast_host() -> str:
    return '<div class="toast-host" id="toast-host" aria-live="polite"></div>'


def progress_bar(percent: int, *, label: str = "", tone: str = "brand") -> str:
    value = max(0, min(100, int(percent)))
    return f"""
    <div class="progress">
      {f'<div class="progress-head"><span>{esc(label)}</span><span>{value}%</span></div>' if label else ''}
      <div class="progress-track" role="progressbar" aria-valuenow="{value}" aria-valuemin="0" aria-valuemax="100">
        <div class="progress-fill progress-{esc(tone)}" style="width:{value}%"></div>
      </div>
    </div>
    """


def progress_ring(percent: int, *, caption: str = "", sub_caption: str = "", size: int = 132) -> str:
    value = max(0, min(100, int(percent)))
    radius = (size - 18) / 2
    circumference = 2 * 3.14159 * radius
    offset = circumference * (1 - value / 100)
    center = size / 2
    return f"""
    <div class="ring" style="--ring-size:{size}px">
      <svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" aria-label="{esc(caption)} {value}%">
        <circle class="ring-track" cx="{center}" cy="{center}" r="{radius}" fill="none" stroke-width="10"/>
        <circle class="ring-value" cx="{center}" cy="{center}" r="{radius}" fill="none" stroke-width="10"
                stroke-linecap="round" stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{offset:.1f}"
                transform="rotate(-90 {center} {center})"/>
      </svg>
      <div class="ring-center">
        <span class="ring-value-text">{value}%</span>
        {f'<span class="ring-caption">{esc(caption)}</span>' if caption else ''}
      </div>
      {f'<p class="ring-sub">{esc(sub_caption)}</p>' if sub_caption else ''}
    </div>
    """


def avatar(name: str, *, image_url: str = "", size: str = "md", tone: str = "brand") -> str:
    initials = "".join(part[0] for part in (name or "?").split(" ")[:2]).upper()
    if image_url:
        inner = f'<img src="{esc(image_url)}" alt="{esc(name)}" loading="lazy">'
    else:
        inner = f"<span>{esc(initials)}</span>"
    return f'<span class="avatar avatar-{esc(size)} avatar-{esc(tone)}">{inner}</span>'


def empty_state(title: str, message: str, *, icon_name: str = "sparkles", action: str = "") -> str:
    """A finished-looking screen for the no-content case (37)."""
    return f"""
    <div class="empty-state">
      <span class="empty-icon">{icon(icon_name, size=26)}</span>
      <h3>{esc(title)}</h3>
      <p>{esc(message)}</p>
      {f'<div class="empty-action">{action}</div>' if action else ''}
    </div>
    """


def skeleton(*, lines: int = 3, css_class: str = "") -> str:
    """Loading placeholder (38). Client code swaps it out when data arrives."""
    rows = join([f'<span class="skeleton-line" style="width:{95 - index * 14}%"></span>' for index in range(lines)])
    return f'<div class="skeleton {esc(css_class)}" aria-hidden="true">{rows}</div>'


def modal(modal_id: str, title: str, body: str, *, footer: str = "") -> str:
    return f"""
    <div class="modal" id="{esc(modal_id)}" hidden data-modal>
      <div class="modal-backdrop" data-modal-close></div>
      <div class="modal-panel" role="dialog" aria-modal="true" aria-label="{esc(title)}">
        <header class="modal-head">
          <h3>{esc(title)}</h3>
          <button class="btn-icon btn-icon-ghost" type="button" data-modal-close aria-label="סגירה">{icon("close", size=18)}</button>
        </header>
        <div class="modal-body">{body}</div>
        {f'<footer class="modal-foot">{footer}</footer>' if footer else ''}
      </div>
    </div>
    """


# ----------------------------------------------------------------- media ----
_MEDIA_TONES = ("a", "b", "c", "d", "e", "f")


def media(
    *,
    seed: str,
    label: str = "",
    image_url: str = "",
    icon_name: str = "dumbbell",
    ratio: str = "16x9",
    overlay: str = "",
) -> str:
    """A thumbnail.

    When a real asset exists it is used. Otherwise a deterministic gradient
    stands in — a labelled placeholder rather than a broken ``<img>`` (37, 50).
    """
    tone = _MEDIA_TONES[sum(ord(character) for character in (seed or "x")) % len(_MEDIA_TONES)]
    if image_url:
        inner = f'<img src="{esc(image_url)}" alt="{esc(label)}" loading="lazy">'
    else:
        inner = f'<span class="media-glyph">{icon(icon_name, size=30)}</span>'
    return f"""
    <div class="media media-{esc(ratio)} media-tone-{tone}">
      {inner}
      {overlay}
    </div>
    """


def play_overlay(duration_label: str = "") -> str:
    return (
        '<span class="media-play">' + icon("play", size=18) + "</span>"
        + (f'<span class="media-duration">{esc(duration_label)}</span>' if duration_label else "")
    )


# ---------------------------------------------------------- domain cards ----
def video_card(
    *,
    video_id: int,
    title: str,
    duration: int,
    difficulty_label: str,
    category_label: str,
    href: str,
    image_url: str = "",
    completed: bool = False,
    coach_name: str = "",
) -> str:
    return f"""
    <a class="content-card video-card{' is-complete' if completed else ''}" href="{esc(href)}">
      {media(seed=f"video-{video_id}", label=title, image_url=image_url, icon_name="dumbbell",
             overlay=play_overlay(f"{duration} דק׳"))}
      <div class="content-card-body">
        <div class="content-card-tags">
          {badge(category_label, tone="soft")}{badge(difficulty_label, tone="outline")}
          {badge("הושלם", tone="success", icon_name="check") if completed else ""}
        </div>
        <h3 class="content-card-title">{esc(title)}</h3>
        <p class="content-card-meta">{esc(coach_name)}{' · ' if coach_name else ''}{duration} דקות</p>
      </div>
    </a>
    """


def program_card(
    *,
    program_id: int,
    name: str,
    description: str,
    weeks: int,
    difficulty_label: str,
    href: str,
    active: bool = False,
) -> str:
    return f"""
    <a class="content-card program-card{' is-active' if active else ''}" href="{esc(href)}">
      {media(seed=f"program-{program_id}", label=name, icon_name="program", ratio="3x2")}
      <div class="content-card-body">
        <div class="content-card-tags">
          {badge(f"{weeks} שבועות", tone="soft")}{badge(difficulty_label, tone="outline")}
          {badge("התוכנית שלך", tone="brand") if active else ""}
        </div>
        <h3 class="content-card-title">{esc(name)}</h3>
        <p class="content-card-desc">{esc(description)}</p>
      </div>
    </a>
    """


def recipe_card(
    *,
    recipe_id: int,
    name: str,
    meal_label: str,
    prep_minutes: int,
    href: str,
    image_url: str = "",
    tags: Iterable[str] = (),
) -> str:
    tag_html = join([badge(tag, tone="soft") for tag in list(tags)[:2]])
    return f"""
    <a class="content-card recipe-card" href="{esc(href)}">
      {media(seed=f"recipe-{recipe_id}", label=name, image_url=image_url, icon_name="meal", ratio="3x2")}
      <div class="content-card-body">
        <div class="content-card-tags">{badge(meal_label, tone="outline")}{tag_html}</div>
        <h3 class="content-card-title">{esc(name)}</h3>
        <p class="content-card-meta">{icon("clock", size=14)} {prep_minutes} דקות הכנה</p>
      </div>
    </a>
    """


# ----------------------------------------------------------------- table ----
def table(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    empty_message: str = "אין נתונים להצגה",
    css_class: str = "",
) -> str:
    if not rows:
        return empty_state("אין עדיין נתונים", empty_message, icon_name="chart")
    head = join([f"<th>{esc(column)}</th>" for column in columns])
    body = join(
        [
            "<tr>" + join([f"<td>{cell}</td>" for cell in row]) + "</tr>"
            for row in rows
        ]
    )
    return f"""
    <div class="table-wrap {esc(css_class)}">
      <table class="table">
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def tabs(items: Sequence[tuple[str, str, bool]]) -> str:
    """items = (label, href, is_active)."""
    return (
        '<nav class="tabs">'
        + join(
            [
                f'<a class="tab{" is-active" if active else ""}" href="{esc(href)}">{esc(label)}</a>'
                for label, href, active in items
            ]
        )
        + "</nav>"
    )


def filter_chip(label: str, href: str, active: bool = False) -> str:
    return f'<a class="chip{" is-active" if active else ""}" href="{esc(href)}">{esc(label)}</a>'


def price_display(cents: int, suffix: str = "") -> str:
    suffix_html = f'<span class="price-suffix">{esc(suffix)}</span>' if suffix else ""
    return f'<span class="price"><span class="price-value">{esc(money(cents))}</span>{suffix_html}</span>'
