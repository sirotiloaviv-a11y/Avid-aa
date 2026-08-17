"""Conversational AI layer — a Karen/EDITH-style assistant over the monitor.

You message the bot in a private Telegram chat and it answers in Hebrew about
the live state of the system: what fired, from where, which sources are healthy,
what is being watched. It reads that state through tools rather than being told
it in the prompt, so its answers reflect the monitor as it is right now.

Built on the Anthropic API with the async tool runner, which drives the
call → execute → loop cycle over the tools defined below.

TWO RULES THIS MODULE IS BUILT AROUND
-------------------------------------
1. **It must never invent an event.** A security assistant that hallucinates an
   attack is worse than no assistant. Every factual claim has to come from a
   tool result; the system prompt says so, and the tools return "nothing found"
   rather than empty context so the model has something concrete to report.
2. **It answers one chat only.** The monitor routes private messages to it only
   from ``TELEGRAM_ALERT_CHAT_ID``. Without that check, anyone who finds the
   bot could spend the API budget.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic, beta_async_tool
from anthropic import APIError, APIStatusError, RateLimitError

from .alerts import Alert
from .config import Config
from .keywords import Severity
from .monitoring import Runtime

log = logging.getLogger(__name__)

MAX_TOKENS = 16000
MAX_TOOL_ITERATIONS = 8
DEFAULT_HISTORY_TURNS = 12

SYSTEM_PROMPT = """\
את {name}, מערכת העוזרת של מערכת ההתראות הביטחוניות של {owner}.
את מדברת עברית, בגוף ראשון, ישירות אליו.

מי את: הממשק לדבר עם המערכת. את לא זו ששולחת את ההתראות — הן מגיעות אליו
ממילא. התפקיד שלך הוא לענות על שאלות לגביהן, לתת הקשר, ולהצביע על דפוסים
שהוא לא היה שם לב אליהם בזרם הודעות גולמי.

איך את מדברת:
- קצר. שתיים-שלוש שורות לשאלה רגילה. בלי הקדמות, בלי "כמובן" ובלי לחזור על השאלה.
- רגועה ועניינית, גם כשהתוכן חמור. בלי דרמטיזציה, בלי סימני קריאה, בלי אימוג'ים.
- כשיש מספרים — תגידי אותם. "ארבע התראות בשעה האחרונה" עדיף על "כמה התראות".
- אם הוא שואל שאלה קצרה, תעני בשורה אחת.

הכלל הקריטי: לעולם אל תמציאי אירוע. כל טענה עובדתית על מה שקרה, מתי, ומאיפה —
חייבת להגיע מתוצאת כלי שהרצת עכשיו. אם הכלי לא החזיר כלום, תגידי שאין נתונים.
"אין התראות בשעתיים האחרונות" זו תשובה טובה; ניחוש הוא לא. אם משהו לא ברור לך,
תגידי שאת לא יודעת ותציעי מה כן אפשר לבדוק.

הבחנה שחשוב שתשמרי עליה: המערכת מנטרת פידי חדשות וערוצי טלגרם. היא מדווחת מה
שמקורות פרסמו, בהשהיה שלהם. היא לא מערכת התרעה בזמן אמת ואינה תחליף לפיקוד
העורף. אם הוא שואל "יש עכשיו אזעקה?" — את יכולה לומר רק מה שדווח למערכת, ולציין
שזה מה שהמקורות פרסמו ולא התרעה רשמית.

הזמן כרגע: {now}.
"""


class SecurityAssistant:
    """Answers questions about the running monitor, in Hebrew."""

    def __init__(
        self,
        config: Config,
        runtime: Runtime,
        client: Any | None = None,
    ):
        self._config = config
        self._runtime = runtime
        self._client = client or AsyncAnthropic(api_key=config.anthropic_api_key)
        self._history: deque[dict[str, Any]] = deque(
            maxlen=config.assistant_history_turns * 2
        )
        self._tools = self._build_tools()

    # ------------------------------------------------------------- tools
    def _build_tools(self) -> list[Any]:
        """Tools are closures over the live Runtime, so they read current state."""
        runtime = self._runtime
        config = self._config

        @beta_async_tool
        async def get_status() -> str:
            """Current state of the monitor: uptime, alert counts, and the health
            of every source it is watching. Call this for any question about how
            the system itself is doing."""
            snapshot = runtime.snapshot()
            lines = [
                f"זמן פעילות: {snapshot['uptime_seconds'] // 60} דקות",
                f"התראות שנשלחו: {snapshot['alerts_sent']}",
                f"כשלי שליחה: {snapshot['alerts_failed']}",
                f"מילות מפתח פעילות: {len(config.matcher.rules)}",
            ]
            if snapshot["last_alert_at"]:
                ago = int(time.time() - snapshot["last_alert_at"])
                lines.append(f"התראה אחרונה: לפני {ago} שניות")
            else:
                lines.append("התראה אחרונה: אין עדיין")

            lines.append("")
            lines.append("מקורות:")
            for source in snapshot["sources"]:
                last = source["last_success"]
                seen = f"לפני {int(time.time() - last)} שניות" if last else "אף פעם"
                line = (
                    f"- {source['name']} ({source['kind']}): {source['status']}, "
                    f"עדכון אחרון {seen}, {source['items_seen']} פריטים, "
                    f"{source['alerts_raised']} התראות"
                )
                if source["last_error_message"]:
                    line += f", שגיאה אחרונה: {source['last_error_message']}"
                lines.append(line)
            return "\n".join(lines)

        @beta_async_tool
        async def recent_alerts(limit: int = 10, severity: str = "") -> str:
            """Alerts the system has raised, newest first. Call this whenever he
            asks what happened, what came in, whether it has been quiet, or
            about any period of time.

            Args:
                limit: how many to return, at most 50.
                severity: optional filter — CRITICAL, HIGH, ELEVATED or INFO.
                    Leave empty for all severities.
            """
            records = list(runtime.alerts)
            if severity:
                wanted = severity.strip().upper()
                records = [r for r in records if r.severity == wanted]
            records = records[: max(1, min(limit, 50))]
            if not records:
                return "לא נמצאו התראות התואמות."
            return "\n".join(_format_record(r) for r in records)

        @beta_async_tool
        async def search_alerts(query: str, limit: int = 10) -> str:
            """Search the alert history by free text. Matches against the alert
            title, its source, and the keywords that triggered it. Call this
            when he asks about a specific place, event or source rather than
            about recent activity in general.

            Args:
                query: the text to look for, in Hebrew or English.
                limit: how many results to return, at most 50.
            """
            needle = query.strip().lower()
            if not needle:
                return "צריך טקסט לחיפוש."
            hits = [
                r
                for r in runtime.alerts
                if needle in r.title.lower()
                or needle in r.source.lower()
                or any(needle in phrase.lower() for phrase in r.phrases)
            ][: max(1, min(limit, 50))]
            if not hits:
                return f"אין התראות בהיסטוריה שמכילות '{query}'."
            return "\n".join(_format_record(r) for r in hits)

        @beta_async_tool
        async def list_keywords(severity: str = "") -> str:
            """The keywords the monitor is currently filtering for, with the
            severity assigned to each.

            Args:
                severity: optional filter — CRITICAL, HIGH, ELEVATED or INFO.
            """
            rules = config.matcher.rules
            if severity:
                wanted = severity.strip().upper()
                rules = tuple(r for r in rules if r.severity.name == wanted)
            if not rules:
                return "אין מילות מפתח ברמה הזו."
            by_severity: dict[str, list[str]] = {}
            for rule in rules:
                by_severity.setdefault(rule.severity.name, []).append(rule.phrase)
            return "\n".join(
                f"{name} ({len(phrases)}): {', '.join(phrases)}"
                for name, phrases in by_severity.items()
            )

        @beta_async_tool
        async def camera_status() -> str:
            """Whether the local RTSP cameras are wired up, and how."""
            if not config.cameras_enabled:
                return (
                    "המצלמות מושבתות. שכבת הקוד קיימת אבל לא מחוברת — "
                    "הסקריפט רץ בענן והמצלמות ברשת מקומית, אז צריך גשר "
                    "(סוכן מקומי שדוחף תמונות, VPN, או מנהרה יוצאת)."
                )
            return (
                f"מצלמות מופעלות. מצרפת תמונות להתראות ברמת "
                f"{config.camera_snapshot_on_severity} ומעלה."
            )

        return [get_status, recent_alerts, search_alerts, list_keywords, camera_status]

    # ------------------------------------------------------------ prompts
    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            name=self._config.assistant_name,
            owner=self._config.assistant_owner_name,
            now=datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M"),
        )

    # ------------------------------------------------------------- replies
    async def reply(self, user_text: str) -> str:
        """Answer one message from the owner. Returns text ready to send."""
        self._history.append({"role": "user", "content": user_text})
        try:
            message = await self._run(list(self._history))
        except (RateLimitError, APIStatusError, APIError) as exc:
            log.error("Assistant call failed: %s", exc)
            self._history.pop()  # don't leave an unanswered turn in history
            return "לא הצלחתי להגיע למודל כרגע. תנסה שוב בעוד רגע."

        text = _text_of(message)
        if not text:
            self._history.pop()
            return "לא קיבלתי תשובה. תנסה לנסח אחרת."
        self._history.append({"role": "assistant", "content": text})
        return text

    async def brief(self, alert: Alert) -> str | None:
        """A short read on a just-fired alert, for the highest severities.

        Deliberately kept out of the conversation history: this is commentary on
        an event, not a turn in a dialogue, and threading it in would make the
        next question arrive with a stale alert attached to it.
        """
        prompt = (
            "התקבלה עכשיו התראה. תני שורה אחת של הקשר — האם זה משתלב במשהו "
            "שכבר נראה בהיסטוריה, או שזה אירוע בודד. אם אין שום דבר להוסיף "
            "מעבר למה שכתוב בהתראה עצמה, תעני בדיוק: אין הקשר נוסף.\n\n"
            f"מקור: {alert.source}\n"
            f"חומרה: {alert.severity.name}\n"
            f"מילות מפתח: {', '.join(alert.phrases)}\n"
            f"כותרת: {alert.title}"
        )
        try:
            message = await self._run([{"role": "user", "content": prompt}])
        except (RateLimitError, APIStatusError, APIError) as exc:
            log.warning("Assistant brief failed: %s", exc)
            return None

        text = _text_of(message).strip()
        if not text or "אין הקשר נוסף" in text:
            return None
        return text

    async def _run(self, messages: list[dict[str, Any]]):
        runner = self._client.beta.messages.tool_runner(
            model=self._config.assistant_model,
            max_tokens=MAX_TOKENS,
            system=self._system_prompt(),
            tools=self._tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self._config.assistant_effort},
            max_iterations=MAX_TOOL_ITERATIONS,
        )
        return await runner.until_done()

    def reset(self) -> None:
        """Drop the conversation history (the /reset command)."""
        self._history.clear()


# --------------------------------------------------------------- helpers
def _text_of(message: Any) -> str:
    """Concatenate the text blocks of a response, ignoring thinking blocks."""
    parts = [
        block.text
        for block in getattr(message, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def _format_record(record: Any) -> str:
    when = datetime.fromtimestamp(record.timestamp, tz=timezone.utc).astimezone()
    line = (
        f"[{when:%d/%m %H:%M}] {record.severity} · {record.source} · "
        f"{record.title} · מילות מפתח: {', '.join(record.phrases)}"
    )
    if not record.delivered:
        line += " (השליחה נכשלה)"
    return line


def severity_at_least(name: str, floor: Severity) -> bool:
    """True when a severity name is at or above ``floor``."""
    try:
        return Severity[name.upper()] >= floor
    except KeyError:
        return False
