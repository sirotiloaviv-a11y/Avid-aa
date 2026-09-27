"""The bot process: owns the state, the engines and every service around them.

Exactly one :class:`BotRuntime` may run per state directory. It holds
``state/bot.lock`` for its whole life; operator tools check that lock and,
while it is held, queue control requests instead of writing account state
(see :mod:`trading_bot.risk_manager.controls`).

With ``TRADING_ENABLED=true`` it also runs the trading loop
(:mod:`trading_bot.main`): feeds → strategy → risk engine → brokers.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Settings
from .dashboard import DashboardApp, DashboardServer
from .risk_manager import ControlPoller, NewsGuard, OperatorControls, RiskManager, build_news_guard
from .telegram_bot import TelegramService

if TYPE_CHECKING:
    from .main import TradingLoop
from .utils import ProcessLock, StateStore, get_logger

log = get_logger(__name__)


class AlreadyRunning(RuntimeError):
    """Another bot process holds the state directory."""


def state_dir(settings: Settings) -> Path:
    return settings.state_db_path.parent


def kill_switch_path(settings: Settings) -> Path:
    return state_dir(settings) / "KILL"


def lock_path(settings: Settings) -> Path:
    return state_dir(settings) / "bot.lock"


class BotRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        enable_telegram: bool = True,
        enable_dashboard: bool = True,
        enable_trading: bool = True,
    ) -> None:
        self.settings = settings
        self.lock = ProcessLock(lock_path(settings))
        if not self.lock.acquire():
            raise AlreadyRunning(f"another bot process holds {self.lock.path}")
        try:
            self.store = StateStore(settings.state_db_path)
            self.news_guard: NewsGuard = build_news_guard(settings.news)
            self.manager = RiskManager.from_settings(
                settings, self.store, news_guard=self.news_guard,
                kill_switch_path=kill_switch_path(settings),
            )
            self.controls = OperatorControls(self.manager, kill_switch_path(settings))
            self.poller = ControlPoller(self.controls, self.store)
            self.telegram: TelegramService | None = None
            if enable_telegram and settings.telegram.enabled:
                self.telegram = TelegramService(
                    settings, self.manager, self.store,
                    news_guard=self.news_guard, controls=self.controls,
                )
            self.dashboard: DashboardServer | None = None
            if enable_dashboard and settings.dashboard.enabled:
                app = DashboardApp(
                    manager=self.manager, controls=self.controls, store=self.store,
                    news_guard=self.news_guard, config=settings.dashboard,
                    environment=settings.environment.value,
                    stale_after=timedelta(seconds=settings.risk.equity_stale_seconds),
                )
                self.dashboard = DashboardServer(app, settings.dashboard.host, settings.dashboard.port)
            self.trading: TradingLoop | None = None
            if enable_trading and settings.trading.enabled:
                from .main import build_trading_loop

                self.trading = build_trading_loop(
                    settings, self.manager, self.store, self.news_guard, alert=self._alert,
                )
        except BaseException:
            self.lock.release()
            raise

    def _alert(self, text: str) -> None:
        if self.telegram is not None:
            self.telegram.notifier.send(text)

    def start(self) -> None:
        # Requests left by a bot that died before applying them are expired.
        self.controls.process_pending(self.store)
        self.poller.start()
        if self.telegram is not None:
            self.telegram.start()
        if self.dashboard is not None:
            self.dashboard.start()
        if self.trading is not None:
            self.trading.start()
        log.info("Bot runtime started: %d account(s), telegram=%s, dashboard=%s, trading=%s",
                 len(self.manager), self.telegram is not None, self.dashboard is not None,
                 self.trading is not None)

    def run_until(self, stop: threading.Event) -> None:
        """Run the trading loop (or just housekeeping) until ``stop`` is set."""
        next_news = 0.0
        while not stop.is_set():
            if time.monotonic() >= next_news:
                self.news_guard.refresh()
                next_news = time.monotonic() + 60
            if self.trading is not None:
                self.trading.step(timeout=1.0)
            else:
                stop.wait(1.0)

    def stop(self) -> None:
        if self.trading is not None:
            self.trading.stop()
        if self.dashboard is not None:
            self.dashboard.stop()
        if self.telegram is not None:
            self.telegram.stop()
        self.poller.stop()
        self.store.close()
        self.lock.release()
        log.info("Bot runtime stopped")
