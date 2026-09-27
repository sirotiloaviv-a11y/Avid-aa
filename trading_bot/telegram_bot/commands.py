"""Operator commands over Telegram: parsing, execution and the polling loop.

Security model: commands are accepted **only** from the chats listed in
``TELEGRAM_CHAT_IDS``. Anything else is logged and ignored without a reply,
so a stranger who finds the bot learns nothing and controls nothing.

Commands older than :data:`MAX_COMMAND_AGE` are dropped, so a ``/resume``
sent during a long outage is not executed hours later when the bot restarts.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence, cast

from ..risk_manager.news_guard import NewsCheck, NewsGuard
from ..risk_manager.risk_engine import RiskManager
from ..utils.logger import get_logger
from ..utils.state_store import StateStore, StateStoreError
from ..utils.time_utils import utc_now
from .api import TelegramApiError, TelegramClient
from .formatter import HELP_TEXT, esc, format_news, format_status
from .notifier import TelegramNotifier

log = get_logger(__name__)

MAX_COMMAND_AGE = timedelta(minutes=2)
OFFSET_KEY = "telegram.update_offset"

_COMMAND = re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@([A-Za-z0-9_]{3,64}))?(?:\s+(.*))?$", re.DOTALL)


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: str = ""


def parse_command(text: str | None, bot_username: str | None = None) -> ParsedCommand | None:
    """Parse ``/cmd``, ``/cmd@BotName`` and ``/cmd args``; None if not a command.

    In group chats, a command addressed to a different bot is ignored.
    """
    if not text:
        return None
    match = _COMMAND.match(text.strip())
    if match is None:
        return None
    name, target, args = match.group(1), match.group(2), match.group(3)
    if target and bot_username and target.lower() != bot_username.lower():
        return None
    return ParsedCommand(name.lower(), (args or "").strip())


class CommandProcessor:
    """Executes parsed commands against the risk manager. Returns HTML replies."""

    def __init__(
        self,
        manager: RiskManager,
        news_guard: NewsGuard | None,
        kill_switch_path: Path,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.manager = manager
        self.news_guard = news_guard
        self.kill_switch_path = kill_switch_path
        self._clock = clock

    def handle(self, command: ParsedCommand, *, operator: str) -> str:
        handlers: dict[str, Callable[[str, str], str]] = {
            "start": lambda _a, _o: HELP_TEXT,
            "help": lambda _a, _o: HELP_TEXT,
            "status": lambda _a, _o: self.status(),
            "news": lambda _a, _o: self.news(),
            "halt": self.halt,
            "resume": lambda _a, o: self.resume(o),
        }
        handler = handlers.get(command.name)
        if handler is None:
            return f"Unknown command /{esc(command.name)}. Send /help for the list."
        try:
            return handler(command.args, operator)
        except Exception as exc:
            log.exception("Telegram command /%s failed", command.name)
            return f"⚠️ /{esc(command.name)} failed: {esc(exc)}"

    def status(self) -> str:
        return format_status(
            self.manager.statuses(),
            kill_switch_active=self.kill_switch_path.exists(),
            now=self._clock(),
        )

    def news(self) -> str:
        now = self._clock()
        if self.news_guard is None or not self.news_guard.enabled:
            return format_news([], NewsCheck(True), enabled=False, now=now)
        check = self.news_guard.check(now)
        events = self.news_guard.upcoming(now, within=timedelta(hours=24))
        return format_news(events, check, enabled=True, now=now)

    def halt(self, args: str, operator: str) -> str:
        reason = args or "emergency halt from Telegram"
        stamp = self._clock().isoformat()
        # The KILL file comes first: it blocks entries in every process that
        # shares this state directory, even if an engine call below fails.
        self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.write_text(f"{stamp} {operator}: {reason}\n", encoding="utf-8")
        log.critical("EMERGENCY HALT via Telegram by %s: %s", operator, reason)
        failed: list[str] = []
        for engine in self.manager:
            try:
                engine.halt(f"{reason} (Telegram, {operator})")
            except Exception:
                log.exception("[%s] Manual halt failed", engine.account.account_id)
                failed.append(engine.account.account_id)
        lines = [
            "🛑 <b>EMERGENCY HALT</b> on all accounts",
            f"Kill switch: <code>{esc(self.kill_switch_path)}</code>",
            f"Reason: {esc(reason)}",
            "Positions are being flattened. Send /resume to clear.",
        ]
        if failed:
            lines.append(f"⚠️ Engine halt failed for: {esc(', '.join(failed))} (KILL file still blocks)")
        return "\n".join(lines)

    def resume(self, operator: str) -> str:
        self.kill_switch_path.unlink(missing_ok=True)
        for engine in self.manager:
            engine.resume_manual_halt()
        log.warning("Manual halt cleared via Telegram by %s", operator)
        still = [s for s in self.manager.statuses() if s.halted]
        lines = ["🟢 <b>Manual halt cleared</b>, kill switch removed."]
        if still:
            lines.append("Still halted by risk limits:")
            for status in still:
                lines.append(f"• <code>{esc(status.account_id)}</code>: {esc('; '.join(status.halt_reasons))}")
        else:
            lines.append("All accounts may trade.")
        return "\n".join(lines)


class CommandResponder:
    """Long-polls ``getUpdates`` and answers authorised operators."""

    def __init__(
        self,
        client: TelegramClient,
        processor: CommandProcessor,
        notifier: TelegramNotifier,
        allowed_chat_ids: Sequence[str],
        store: StateStore,
        *,
        bot_username: str | None = None,
        poll_timeout: int = 25,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.client = client
        self.processor = processor
        self.notifier = notifier
        self.allowed = frozenset(allowed_chat_ids)
        self.store = store
        self.bot_username = bot_username
        self.poll_timeout = poll_timeout
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None

    # ------------------------------------------------------------- offsets
    def _load_offset(self) -> int | None:
        try:
            raw = self.store.get_value(OFFSET_KEY)
        except StateStoreError as exc:
            log.error("Cannot read Telegram offset: %s", exc)
            return None
        return int(raw) if raw and raw.lstrip("-").isdigit() else None

    def _save_offset(self, offset: int) -> None:
        self._offset = offset
        try:
            self.store.set_value(OFFSET_KEY, str(offset))
        except StateStoreError as exc:
            log.error("Cannot save Telegram offset: %s", exc)

    def skip_backlog(self) -> None:
        """First start: acknowledge queued updates without executing them."""
        updates = self.client.get_updates(None, timeout=0)
        if updates:
            last = max(int(u.get("update_id", 0)) for u in updates)
            self._save_offset(last + 1)
            log.info("Skipped %d queued Telegram update(s) from before first start", len(updates))

    # ------------------------------------------------------------ handling
    def handle_update(self, update: dict[str, Any]) -> None:
        update_id = int(update.get("update_id", 0))
        # Advance first: a command that crashes the handler must not replay forever.
        self._save_offset(update_id + 1)
        message = cast("dict[str, Any] | None", update.get("message"))
        if not message:
            return
        chat = cast("dict[str, Any]", message.get("chat") or {})
        sender = cast("dict[str, Any]", message.get("from") or {})
        chat_id = str(chat.get("id", ""))
        command = parse_command(cast("str | None", message.get("text")), self.bot_username)
        if command is None:
            return
        operator = sender.get("username") or str(sender.get("id", "unknown"))
        if chat_id not in self.allowed:
            log.warning("Ignored /%s from unauthorised chat %s (user %s)", command.name, chat_id, operator)
            return
        sent_at = datetime.fromtimestamp(int(message.get("date", 0)), timezone.utc)
        if self._clock() - sent_at > MAX_COMMAND_AGE:
            log.warning("Ignored stale /%s from %s sent at %s", command.name, operator, sent_at)
            self.notifier.send(
                f"⏱ Ignored /{esc(command.name)} sent at {sent_at:%H:%M:%S} UTC: too old. Send it again.",
                chat_ids=[chat_id],
            )
            return
        log.info("Telegram command /%s from %s", command.name, operator)
        self.notifier.send(self.processor.handle(command, operator=str(operator)), chat_ids=[chat_id])

    def poll_once(self) -> None:
        for update in self.client.get_updates(self._offset, timeout=self.poll_timeout):
            self.handle_update(update)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-commands", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        self._offset = self._load_offset()
        failures = 0
        while not self._stop.is_set():
            try:
                if self._offset is None:
                    self.skip_backlog()
                    if self._offset is None:
                        self._offset = 0
                self.poll_once()
                failures = 0
            except TelegramApiError as exc:
                failures += 1
                # 409: another instance is polling this token, or a webhook is set.
                delay = exc.retry_after or min(60.0, 2.0 ** failures)
                if exc.status == 409:
                    delay = 60.0
                log.error("Telegram polling failed (%s); retrying in %.0fs", exc, delay)
                self._stop.wait(delay)
            except Exception:
                failures += 1
                log.exception("Telegram command loop error")
                self._stop.wait(min(60.0, 2.0 ** failures))
