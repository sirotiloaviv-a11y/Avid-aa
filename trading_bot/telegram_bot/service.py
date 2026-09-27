"""Builds and runs the whole Telegram layer from :class:`Settings`.

Run it in the **same process** as the risk engines it reports on: events are
delivered in-process, and ``/halt`` / ``/resume`` act on those engines
directly. (The ``state/KILL`` file that ``/halt`` writes also blocks entries
in any other process sharing the state directory.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from ..config import Settings
from ..risk_manager.news_guard import NewsGuard
from ..risk_manager.risk_engine import RiskManager
from ..utils.logger import get_logger
from ..utils.state_store import StateStore
from .api import TelegramApiError, TelegramClient
from .commands import CommandProcessor, CommandResponder
from .formatter import esc
from .notifier import TelegramNotifier
from .scheduler import DailySummaryScheduler

log = get_logger(__name__)


class TelegramService:
    def __init__(
        self,
        settings: Settings,
        manager: RiskManager,
        store: StateStore,
        *,
        news_guard: NewsGuard | None,
        kill_switch_path: Path,
        client: TelegramClient | None = None,
    ) -> None:
        config = settings.telegram
        if not config.enabled:
            raise ValueError("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS)")
        self.settings = settings
        self.client = client or TelegramClient(config.bot_token, api_base=config.api_base)
        self.notifier = TelegramNotifier(self.client, config.chat_ids)
        self.notifier.attach(manager)
        self.manager = manager
        self.responder: CommandResponder | None = None
        if config.commands_enabled:
            processor = CommandProcessor(manager, news_guard, kill_switch_path)
            self.responder = CommandResponder(
                self.client, processor, self.notifier, config.chat_ids, store,
                bot_username=self._bot_username(),
            )
        self.scheduler: DailySummaryScheduler | None = None
        if config.daily_summary:
            self.scheduler = DailySummaryScheduler(
                manager, self.notifier, settings.session, store,
                lead_minutes=config.summary_lead_minutes,
            )

    def _bot_username(self) -> str | None:
        try:
            me = self.client.call("getMe", {})
        except TelegramApiError as exc:
            log.warning("getMe failed (%s); group-chat @mentions will not be filtered", exc)
            return None
        if not isinstance(me, dict):
            return None
        username = cast("dict[str, Any]", me).get("username")
        return str(username) if username else None

    def start(self) -> None:
        self.notifier.start()
        if self.responder is not None:
            self.responder.start()
        if self.scheduler is not None:
            self.scheduler.start()
        halted = [s.account_id for s in self.manager.statuses() if s.halted]
        text = (f"🟢 <b>Trading bot started</b> · {esc(self.settings.environment.value)} · "
                f"{len(self.manager)} account(s)")
        if halted:
            text += f"\n🛑 Halted: {esc(', '.join(halted))}"
        self.notifier.send(text, silent=True)
        log.info("Telegram service started")

    def stop(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop()
        if self.responder is not None:
            self.responder.stop()
        self.notifier.send("⏹ <b>Trading bot stopping</b>", silent=True)
        self.notifier.stop()
        log.info("Telegram service stopped")
