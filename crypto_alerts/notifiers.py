"""Notification channels and the dispatcher that fans alerts out to them.

Every message is a :class:`Notification` with an ``urgent`` flag. Each channel
decides whether it wants a given message (``accepts``) and delivers it with
its own retries; the dispatcher sends to all accepting channels concurrently,
so a slow or failing channel never delays or blocks the others.

Channels
--------
* Telegram (``telegram_bot.TelegramNotifier``) — every alert. Urgent alerts
  are also copied to ``TELEGRAM_URGENT_CHAT_ID`` if set; give that chat its
  own notification sound in the Telegram app. Bots cannot choose a sound
  per message, so a dedicated chat is how you get one.
* Pushover — urgent alerts (or all, with ``PUSHOVER_URGENT_ONLY=false``) with
  a chosen sound and priority. Priority 2 (emergency) repeats until you
  acknowledge it, which is the only option here that will wake you up.
* Local sound — runs ``SOUND_COMMAND`` on the machine hosting the bot.
* Console — ``DRY_RUN=true``.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notification:
    text: str  # Telegram HTML
    title: str = "Crypto alert"
    # Plain-text version for channels with tight length limits (Pushover: 1024).
    short_text: str = ""
    urgent: bool = False
    kind: str = "alert"  # "alert" | "system"


class Channel(Protocol):
    name: str

    def accepts(self, notification: Notification) -> bool: ...

    async def send(self, notification: Notification) -> bool: ...


_TAG = re.compile(r"<[^>]+>")


def html_to_text(text: str) -> str:
    """Strip Telegram HTML to plain text."""
    return html.unescape(_TAG.sub("", text))


class ConsoleChannel:
    """Prints messages instead of sending them (DRY_RUN=true)."""

    name = "console"

    def accepts(self, notification: Notification) -> bool:
        return True

    async def send(self, notification: Notification) -> bool:
        banner = "🚨 URGENT " if notification.urgent else ""
        print(f"\n{'=' * 60}\n{banner}{html_to_text(notification.text)}\n{'=' * 60}", flush=True)
        return True


# ------------------------------------------------------------------- Pushover

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_MAX_MESSAGE = 1024
PUSHOVER_MAX_TITLE = 250

async def _urllib_post(url: str, fields: dict[str, str]) -> tuple[int, str]:
    """POST a form with the standard library, off the event loop."""

    def post() -> tuple[int, str]:
        data = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    return await asyncio.to_thread(post)


class PushoverChannel:
    """Pushover push notifications with priority and sound.

    Pushover renders a small HTML subset (<b>, <i>, <u>, <font>, <a>), so the
    compact ``short_text`` is sent with ``html=1``.
    """

    name = "pushover"

    def __init__(
        self,
        token: str,
        user: str,
        *,
        priority: int = 1,
        sound: str = "cashregister",
        urgent_only: bool = True,
        max_attempts: int = 3,
        post: Optional[Callable[[str, dict[str, str]], Any]] = None,
    ) -> None:
        self._token = token
        self._user = user
        self.priority = priority
        self.sound = sound
        self.urgent_only = urgent_only
        self.max_attempts = max_attempts
        self._post = post or _urllib_post

    def accepts(self, notification: Notification) -> bool:
        if notification.kind == "system":
            return False
        return notification.urgent or not self.urgent_only

    def _fields(self, notification: Notification) -> dict[str, str]:
        body = notification.short_text or html_to_text(notification.text)
        priority = self.priority if notification.urgent else min(self.priority, 0)
        fields = {
            "token": self._token,
            "user": self._user,
            "title": notification.title[:PUSHOVER_MAX_TITLE],
            "message": body[:PUSHOVER_MAX_MESSAGE],
            "html": "1",
            "priority": str(priority),
        }
        if self.sound:
            fields["sound"] = self.sound
        if priority == 2:  # emergency: repeat every 60s for up to 30 min until acknowledged
            fields["retry"] = "60"
            fields["expire"] = "1800"
        return fields

    async def send(self, notification: Notification) -> bool:
        fields = self._fields(notification)
        delay = 2.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                status, body = await self._post(PUSHOVER_URL, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # network error
                status, body = 0, repr(exc)
            if 200 <= status < 300:
                return True
            if 400 <= status < 500 and status != 429:
                log.error("Pushover rejected the message (%s): %s", status, _pushover_errors(body))
                return False
            if attempt < self.max_attempts:
                log.warning("Pushover send failed (%s); retry %d in %.0fs", status or body, attempt, delay)
                await asyncio.sleep(delay)
                delay *= 2
        log.error("Pushover send failed after %d attempts", self.max_attempts)
        return False


def _pushover_errors(body: str) -> str:
    try:
        return "; ".join(json.loads(body).get("errors", [])) or body[:200]
    except (ValueError, AttributeError):
        return body[:200]


# ---------------------------------------------------------------------- sound


class SoundChannel:
    """Plays a sound on the host by running ``SOUND_COMMAND`` (no shell).

    With no command it rings the terminal bell, which most terminals turn into
    a sound or a flash.
    """

    name = "sound"

    def __init__(self, command: str = "", urgent_only: bool = True, timeout: float = 15.0) -> None:
        self.argv = shlex.split(command) if command else []
        self.urgent_only = urgent_only
        self.timeout = timeout

    def accepts(self, notification: Notification) -> bool:
        if notification.kind == "system":
            return False
        return notification.urgent or not self.urgent_only

    async def send(self, notification: Notification) -> bool:
        if not self.argv:
            sys.stdout.write("\a")
            sys.stdout.flush()
            return True
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
        except OSError as exc:
            log.error("SOUND_COMMAND could not start: %s", exc)
            return False
        try:
            return await asyncio.wait_for(proc.wait(), self.timeout) == 0
        except asyncio.TimeoutError:
            proc.kill()
            return False


# ----------------------------------------------------------------- dispatcher


@dataclass
class ChannelStats:
    sent: int = 0
    failed: int = 0
    last_error: Optional[str] = None


class AlertDispatcher:
    """Queue in front of the channels so producers never block on the network."""

    def __init__(self, channels: list[Channel], maxsize: int = 200) -> None:
        self.channels = list(channels)
        self._queue: asyncio.Queue[Notification] = asyncio.Queue(maxsize=maxsize)
        self.stats: dict[str, ChannelStats] = {c.name: ChannelStats() for c in self.channels}
        self.dropped = 0

    def enqueue(self, notification: Notification | str) -> None:
        if isinstance(notification, str):
            notification = Notification(text=notification, kind="system")
        try:
            self._queue.put_nowait(notification)
        except asyncio.QueueFull:
            self.dropped += 1
            log.error("Alert queue full — dropping: %s", notification.title)

    async def run(self) -> None:
        """Worker loop: deliver queued messages until cancelled."""
        while True:
            notification = await self._queue.get()
            try:
                await self._deliver(notification)
            finally:
                self._queue.task_done()

    async def _deliver(self, notification: Notification) -> None:
        targets = [c for c in self.channels if c.accepts(notification)]
        results = await asyncio.gather(*(c.send(notification) for c in targets), return_exceptions=True)
        for channel, result in zip(targets, results):
            stats = self.stats.setdefault(channel.name, ChannelStats())
            if result is True:
                stats.sent += 1
            else:
                stats.failed += 1
                stats.last_error = repr(result) if isinstance(result, BaseException) else "send failed"
                if isinstance(result, BaseException):
                    log.error("%s channel raised: %r", channel.name, result)

    async def drain(self, timeout: float = 10.0) -> None:
        """Wait (bounded) for queued messages to go out, e.g. before shutdown."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
        except asyncio.TimeoutError:
            log.warning("Shutdown with %d message(s) still queued", self._queue.qsize())

    def snapshot(self) -> dict[str, Any]:
        return {
            "queued": self._queue.qsize(),
            "dropped": self.dropped,
            "channels": {
                name: {"sent": s.sent, "failed": s.failed, "last_error": s.last_error}
                for name, s in self.stats.items()
            },
        }
