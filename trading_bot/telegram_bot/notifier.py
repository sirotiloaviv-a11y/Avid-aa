"""Telegram notifier: turns risk events into alerts, delivered off-thread.

The risk engine calls :meth:`TelegramNotifier.handle_event` synchronously, so
that method only formats and enqueues. A single worker thread delivers
messages in order, retrying rate limits and network errors with backoff.
Telegram being slow or unreachable never blocks or breaks the risk engine.
"""

from __future__ import annotations

import html
import queue
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from ..risk_manager.events import (
    DrawdownWarningEvent,
    HaltEvent,
    RiskEvent,
    TradeClosedEvent,
    TradeOpenedEvent,
)
from ..risk_manager.risk_engine import RiskManager
from ..utils.logger import get_logger
from .api import TelegramApiError, TelegramClient
from .formatter import (
    format_drawdown_warning,
    format_halt,
    format_trade_entry,
    format_trade_exit,
    split_message,
)

log = get_logger(__name__)

_TAG = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


@dataclass(frozen=True)
class _Outgoing:
    chat_id: str
    text: str
    silent: bool


_STOP = object()


class TelegramNotifier:
    def __init__(
        self,
        client: TelegramClient,
        chat_ids: Sequence[str],
        *,
        max_queue: int = 1000,
        max_attempts: int = 6,
        max_backoff: float = 60.0,
    ) -> None:
        self.client = client
        self.chat_ids = tuple(chat_ids)
        self.max_attempts = max_attempts
        self.max_backoff = max_backoff
        self._queue: queue.Queue[_Outgoing | object] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._halted_until: Callable[[str], datetime | None] = lambda _account: None

    # --------------------------------------------------------------- wiring
    def attach(self, manager: RiskManager) -> None:
        """Alert on every risk event from every account."""
        self._halted_until = lambda account_id: manager[account_id].status().halted_until
        manager.subscribe(self.handle_event)

    def handle_event(self, event: RiskEvent) -> None:
        """Risk-engine listener. Formats and enqueues; never raises."""
        try:
            if isinstance(event, TradeOpenedEvent):
                self.send(format_trade_entry(event))
            elif isinstance(event, TradeClosedEvent):
                self.send(format_trade_exit(event))
            elif isinstance(event, DrawdownWarningEvent):
                self.send(format_drawdown_warning(event))
            else:
                self.send(format_halt(event, self._resume_time(event)))
        except Exception:
            log.exception("Could not format Telegram alert for %r", event)

    def _resume_time(self, event: HaltEvent) -> datetime | None:
        try:
            return self._halted_until(event.account_id)
        except Exception:
            return None

    # ------------------------------------------------------------ messaging
    def send(self, text: str, *, silent: bool = False, chat_ids: Sequence[str] | None = None) -> None:
        """Queue ``text`` (Telegram HTML) for every alert chat, or ``chat_ids``."""
        for chat_id in chat_ids if chat_ids is not None else self.chat_ids:
            for chunk in split_message(text):
                try:
                    self._queue.put_nowait(_Outgoing(chat_id, chunk, silent))
                except queue.Full:
                    log.error("Telegram queue full; dropped message: %.80s", html_to_plain(chunk))

    def deliver(self, message: _Outgoing) -> bool:
        """Send one message with retries. Returns whether it was delivered."""
        plain = False
        for attempt in range(1, self.max_attempts + 1):
            try:
                if plain:
                    self.client.send_message(message.chat_id, html_to_plain(message.text),
                                             parse_mode="", silent=message.silent)
                else:
                    self.client.send_message(message.chat_id, message.text, silent=message.silent)
                return True
            except TelegramApiError as exc:
                if exc.status == 400 and not plain:
                    # Bad markup must not cost us the alert: resend as plain text.
                    log.warning("Telegram rejected HTML (%s); resending as plain text", exc)
                    plain = True
                    continue
                if not exc.retryable:
                    log.error("Telegram message to %s dropped: %s", message.chat_id, exc)
                    return False
                delay = exc.retry_after or min(self.max_backoff, 2.0 ** attempt)
                log.warning("Telegram send failed (%s); retry %d/%d in %.0fs",
                            exc, attempt, self.max_attempts, delay)
                if self._stop.wait(delay):
                    break
            except Exception:
                log.exception("Unexpected error sending Telegram message")
                return False
        log.error("Telegram message to %s undelivered after retries: %.80s",
                  message.chat_id, html_to_plain(message.text))
        return False

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-notifier", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Deliver what is queued (up to ``timeout``), then stop the worker."""
        if self._thread is None:
            return
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            self._stop.set()
        self._thread.join(timeout)
        self._stop.set()
        self._thread = None

    def flush(self) -> None:
        """Deliver everything queued on the calling thread (CLI and tests)."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _Outgoing):
                self.deliver(item)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if isinstance(item, _Outgoing):
                self.deliver(item)
