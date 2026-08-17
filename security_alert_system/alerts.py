"""The alert record passed from sources to the notifier."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .keywords import Match, Severity

MAX_EXCERPT_CHARS = 700


@dataclass
class Alert:
    """One matched item, ready to be rendered and sent."""

    source: str                    # e.g. "ynet — ביטחון" or "@channel_name"
    source_kind: str               # "rss" | "telegram"
    title: str
    body: str
    matches: list[Match]
    url: str | None = None
    published_at: datetime | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dedupe_key: str = ""

    @property
    def severity(self) -> Severity:
        return max((m.severity for m in self.matches), default=Severity.INFO)

    @property
    def phrases(self) -> list[str]:
        seen: list[str] = []
        for match in self.matches:
            if match.phrase not in seen:
                seen.append(match.phrase)
        return seen

    def to_html(self) -> str:
        """Render for Telegram ``parse_mode=HTML``."""
        esc = html.escape
        sev = self.severity
        lines = [f"{sev.emoji} <b>התראה — רמה {esc(sev.hebrew)}</b>"]

        keywords = " · ".join(esc(p) for p in self.phrases)
        lines.append(f"🔑 <b>מילות מפתח:</b> {keywords}")
        lines.append(f"📡 <b>מקור:</b> {esc(self.source)}")

        if self.title:
            lines.append("")
            lines.append(f"<b>{esc(_clip(self.title, 200))}</b>")

        body = _clip(self.body, MAX_EXCERPT_CHARS)
        if body and body.strip() != self.title.strip():
            lines.append(esc(body))

        if self.url:
            lines.append("")
            lines.append(f'🔗 <a href="{esc(self.url, quote=True)}">לכתבה המלאה</a>')

        stamp = (self.published_at or self.detected_at).astimezone()
        lines.append(f"🕒 {stamp:%d/%m/%Y %H:%M:%S %Z}")
        return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
