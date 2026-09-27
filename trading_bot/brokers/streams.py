"""Self-healing WebSocket stream: reconnects with exponential backoff.

A stream is considered dead, and is reconnected, when the socket errors, the
server closes it, or nothing at all arrives for ``silence_timeout`` seconds
(a half-open TCP connection otherwise looks healthy forever).
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Protocol

from ..utils.logger import get_logger

log = get_logger(__name__)


class MessageSocket(Protocol):
    def send_text(self, text: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | None: ...
    def close(self) -> None: ...


class ReconnectingStream:
    def __init__(
        self,
        name: str,
        connect: Callable[[], MessageSocket],
        on_message: Callable[[str, MessageSocket], None],
        *,
        on_open: Callable[[MessageSocket], None] | None = None,
        heartbeat: Callable[[MessageSocket], None] | None = None,
        heartbeat_interval: float = 20.0,
        silence_timeout: float = 60.0,
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        self.name = name
        self._connect = connect
        self._on_message = on_message
        self._on_open = on_open
        self._heartbeat = heartbeat
        self.heartbeat_interval = heartbeat_interval
        self.silence_timeout = silence_timeout
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self._on_state = on_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.reconnects = 0
        self._backoff = backoff_initial

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name=f"stream-{self.name}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            if self._on_state is not None:
                try:
                    self._on_state(value)
                except Exception:
                    log.exception("[%s] state callback failed", self.name)

    def run(self) -> None:
        self._backoff = self.backoff_initial
        while not self._stop.is_set():
            sock: MessageSocket | None = None
            try:
                sock = self._connect()
                if self._on_open is not None:
                    self._on_open(sock)
                log.info("[%s] stream connected", self.name)
                self._set_connected(True)
                self._pump(sock)
            except Exception as exc:
                log.warning("[%s] stream error: %s", self.name, exc)
            finally:
                self._set_connected(False)
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            self.reconnects += 1
            delay = self._backoff * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not crypto
            log.info("[%s] reconnecting in %.1fs", self.name, delay)
            if self._stop.wait(delay):
                break
            self._backoff = min(self.backoff_max, self._backoff * 2)

    def _pump(self, sock: MessageSocket) -> None:
        last_message = last_beat = time.monotonic()
        while not self._stop.is_set():
            wait = min(1.0, self.heartbeat_interval)
            message = sock.recv(timeout=wait)
            now = time.monotonic()
            if message is not None:
                last_message = now
                self._backoff = self.backoff_initial  # healthy again: reset backoff
                self._on_message(message, sock)
            elif now - last_message > self.silence_timeout:
                raise ConnectionError(f"no data for {self.silence_timeout:.0f}s")
            if self._heartbeat is not None and now - last_beat >= self.heartbeat_interval:
                self._heartbeat(sock)
                last_beat = now
