"""Inline SVG icons.

Inline rather than an icon font or a sprite request: it keeps the CSP tight, the
page single-request, and lets ``currentColor`` do the theming. Icons are drawn
on a 24×24 grid and are direction-neutral except the ones listed in
``FLIPPED``, which are mirrored under RTL (31).
"""

from __future__ import annotations

_PATHS: dict[str, str] = {
    "dashboard": '<path d="M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z"/>',
    "dumbbell": '<path d="M4 9v6M7 7v10M17 7v10M20 9v6M7 12h10" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>',
    "program": '<path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm3 6h8M8 14h8M8 18h5" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "meal": '<path d="M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.5 12a3.5 3.5 0 0 1 7 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    "cart": '<path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.3a2 2 0 0 0 2-1.5L20 8H6.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="10" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2" stroke="currentColor" stroke-width="1.9" fill="none" stroke-linecap="round"/>',
    "community": '<circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 12a3 3 0 1 0 0-6M17 19h3.5a4.5 4.5 0 0 0-3.2-4.3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    "sparkles": '<path d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3Zm6 9l.9 2.3 2.1.8-2.1.8-.9 2.3-.9-2.3-2.1-.8 2.1-.8.9-2.3Z"/>',
    "settings": '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3m14.4-6.4-1.6 1.6M8.2 15.8l-1.6 1.6m0-11.8 1.6 1.6m7.6 7.6 1.6 1.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    "play": '<path d="M8 5.5v13l11-6.5-11-6.5Z"/>',
    "check": '<path d="M4.5 12.5 9 17l10.5-10.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    "arrow": '<path d="M14 5l7 7-7 7M21 12H3" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
    "clock": '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M12 7.5V12l3 1.8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    "flame": '<path d="M12 3s5 4.2 5 8.6A5 5 0 0 1 7 12c0-1.6.7-2.8 1.6-3.8.2 1.4 1 2.1 1.8 2.2C10 8.4 11 5.4 12 3Z"/>',
    "users": '<circle cx="12" cy="8" r="3.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M5 20a7 7 0 0 1 14 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    "credit": '<rect x="3" y="5.5" width="18" height="13" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 10h18M7 15h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    "video": '<rect x="3" y="6" width="12" height="12" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M15 11l6-3.5v9L15 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
    "bell": '<path d="M18 15V10a6 6 0 1 0-12 0v5l-1.6 2.2h15.2L18 15Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M10 20a2 2 0 0 0 4 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/>',
    "female": '<circle cx="12" cy="8.5" r="4.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 13v8M9 18h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "male": '<circle cx="10" cy="14" r="4.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M14 10 20 4m0 0h-5m5 0v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "logo": '<path d="M12 21s-7.5-4.6-7.5-9.8A4.2 4.2 0 0 1 12 8.4a4.2 4.2 0 0 1 7.5 2.8C19.5 16.4 12 21 12 21Z"/><path d="M8.5 12.6h2l1-2.2 1.6 3.6 1-1.4h1.6" fill="none" stroke="#fff" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
    "logout": '<path d="M15 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-2M10 12h11m0 0-3-3m3 3-3 3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    "search": '<circle cx="11" cy="11" r="6" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
    "target": '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="1.3"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M3.5 10h17M8 3.5V6M16 3.5V6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    "shield": '<path d="M12 3.2 19 6v6c0 4.3-3 7.5-7 8.8-4-1.3-7-4.5-7-8.8V6l7-2.8Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="m9 12 2.2 2.2L15.5 10" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
    "plus": '<path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V5.2A1.2 1.2 0 0 1 10.7 4h2.6a1.2 1.2 0 0 1 1.2 1.2V7m2 0v12a1.5 1.5 0 0 1-1.5 1.5h-6A1.5 1.5 0 0 1 7 19V7" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
    "edit": '<path d="M5 19h2.6l9.1-9.1-2.6-2.6L5 16.4V19Zm12.9-11.4 1.5-1.5a1.2 1.2 0 0 0 0-1.7l-.9-.9a1.2 1.2 0 0 0-1.7 0l-1.5 1.5 2.6 2.6Z"/>',
    "info": '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M12 11v5.5M12 7.8v.6" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
    "leaf": '<path d="M20 4c-8 0-14 3.4-14 10a6 6 0 0 0 1.6 4.1C10 15 13 12.4 17 11c-3.3 2-6.6 4.3-9.1 8.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
}

# Icons that carry a direction and must mirror in RTL (31). "play" is not one
# of them: a media triangle points along playback, which stays left-to-right
# even in a right-to-left interface.
FLIPPED = {"arrow", "logout"}


def icon(name: str, *, size: int = 20, css_class: str = "") -> str:
    path = _PATHS.get(name)
    if path is None:
        return ""
    css = ["icon", f"icon-{name}"]
    if name in FLIPPED:
        css.append("icon-flip")
    if css_class:
        css.append(css_class)
    return (
        f'<svg class="{" ".join(css)}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="currentColor" aria-hidden="true" focusable="false">{path}</svg>'
    )


def has_icon(name: str) -> bool:
    return name in _PATHS
