"""End-of-day summary, broadcast just before the prop firm's daily reset.

It fires ``summary_lead_minutes`` before the reset rather than after it:
after the reset each engine rolls its counters over as soon as a new account
snapshot arrives, so "today" would already be empty. The last day sent is
stored, so a restart inside the window does not send it twice.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable

from ..config import SessionConfig
from ..risk_manager.risk_engine import RiskManager
from ..utils.logger import get_logger
from ..utils.state_store import StateStore, StateStoreError
from ..utils.time_utils import ensure_utc, next_reset, trading_day, utc_now
from .formatter import format_daily_summary
from .notifier import TelegramNotifier

log = get_logger(__name__)

LAST_SUMMARY_KEY = "telegram.last_summary_day"


class DailySummaryScheduler:
    def __init__(
        self,
        manager: RiskManager,
        notifier: TelegramNotifier,
        session: SessionConfig,
        store: StateStore,
        *,
        lead_minutes: int = 1,
        check_seconds: float = 20.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if lead_minutes < 1:
            raise ValueError("lead_minutes must be at least 1")
        self.manager = manager
        self.notifier = notifier
        self.session = session
        self.store = store
        self.lead = timedelta(minutes=lead_minutes)
        self.check_seconds = check_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> bool:
        """Send the summary if it is due. Returns whether it was sent."""
        now = ensure_utc(now) if now is not None else self._clock()
        if now < next_reset(now, self.session.reset_tz, self.session.reset_time) - self.lead:
            return False
        day = trading_day(now, self.session.reset_tz, self.session.reset_time)
        try:
            if self.store.get_value(LAST_SUMMARY_KEY) == day.isoformat():
                return False
            self.store.set_value(LAST_SUMMARY_KEY, day.isoformat())
        except StateStoreError as exc:
            log.error("Daily summary bookkeeping failed: %s", exc)
            return False
        self.notifier.send(format_daily_summary(self.manager.statuses(now=now), day))
        log.info("Daily summary for %s queued", day)
        return True

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-summary", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.check_seconds):
            try:
                self.tick()
            except Exception:
                log.exception("Daily summary tick failed")
