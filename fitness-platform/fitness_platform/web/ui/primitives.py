"""HTML building blocks.

Everything that reaches the browser goes through ``esc``. There is no template
engine here on purpose: with a dependency-free stack, an explicit escape at the
single point of interpolation is easier to audit than a global autoescape
setting that one ``|safe`` can undo.
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, Mapping

Markup = str


def esc(value: Any) -> str:
    """Escape a value for use in text or a quoted attribute."""
    if value is None:
        return ""
    return escape(str(value), quote=True)


def raw(value: str) -> str:
    """Mark already-built markup as safe. Only ever called with our own output."""
    return value


def classes(*values: Any) -> str:
    """Join class names, dropping falsy entries."""
    parts: list[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, dict):
            parts.extend(key for key, enabled in value.items() if enabled)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if item)
        else:
            parts.append(str(value))
    return " ".join(parts)


def attrs(mapping: Mapping[str, Any] | None = None, **extra: Any) -> str:
    """Render an attribute string. ``True`` renders bare, ``False``/``None`` drop."""
    merged: dict[str, Any] = dict(mapping or {})
    merged.update(extra)
    out: list[str] = []
    for key, value in merged.items():
        if value is None or value is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        if value is True:
            out.append(name)
        else:
            out.append(f'{name}="{esc(value)}"')
    return (" " + " ".join(out)) if out else ""


def tag(name: str, content: str = "", **attributes: Any) -> str:
    return f"<{name}{attrs(attributes)}>{content}</{name}>"


def void(name: str, **attributes: Any) -> str:
    return f"<{name}{attrs(attributes)}>"


def join(parts: Iterable[str]) -> str:
    return "".join(part for part in parts if part)


def money(cents: int, currency: str = "₪") -> str:
    whole = cents / 100
    formatted = f"{whole:,.0f}" if whole == int(whole) else f"{whole:,.2f}"
    return f"{currency}{formatted}"


def plural_minutes(minutes: int) -> str:
    return "דקה" if minutes == 1 else f"{minutes} דקות"
