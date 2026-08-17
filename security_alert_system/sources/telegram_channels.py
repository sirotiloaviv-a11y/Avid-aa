"""Listens to Telegram channels through the Bot API (long-polling getUpdates).

IMPORTANT LIMITATION — read before configuring channels
-------------------------------------------------------
A bot receives ``channel_post`` updates **only for channels it has been added
to as an administrator**. The Bot API gives no way to read an arbitrary public
channel you do not control; that requires a user account via MTProto
(Telethon / Pyrogram), which means logging in as yourself and accepting the
terms and risks that come with it.

So:

* Channels you own or admin  → add the bot as an admin, list it in
  ``TELEGRAM_CHANNELS``, and this module works directly.
* Public channels you do not control → mirror them into RSS and let the RSS
  monitor handle it. Public channels have a web preview at
  ``https://t.me/s/<channel>``, and bridges such as RSSHub expose that as a
  feed (``https://rsshub.app/telegram/channel/<channel>``). Add those URLs to
  ``RSS_FEEDS`` — same keyword filter, same alerts, no account risk.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..alerts import Alert
from ..config import Config
from ..notifier import Notifier
from ..state import StateStore
from ..telegram_api import TelegramClient, TelegramError

log = logging.getLogger(__name__)

ALLOWED_UPDATES = ["channel_post", "edited_channel_post", "message"]


class TelegramChannelMonitor:
    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        notifier: Notifier,
        state: StateStore,
    ):
        self._config = config
        self._client = client
        self._notifier = notifier
        self._state = state
        # Accept "@name", "name", or a numeric -100... id.
        self._wanted = {c.lstrip("@").lower() for c in config.telegram_channels}

    async def run(self, stop: asyncio.Event) -> None:
        if not self._config.telegram_channels:
            log.info(
                "No TELEGRAM_CHANNELS configured; Telegram listener will still drain "
                "updates so getUpdates does not back up."
            )

        backoff = 2.0
        while not stop.is_set():
            try:
                updates = await self._client.get_updates(
                    offset=self._state.telegram_offset,
                    long_poll_seconds=self._config.telegram_poll_seconds,
                    allowed_updates=ALLOWED_UPDATES,
                )
                backoff = 2.0
            except TelegramError as exc:
                log.error("getUpdates failed: %s (retrying in %.0fs)", exc, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 120)
                continue

            for update in updates:
                # Always advance the offset, even for updates we ignore,
                # otherwise Telegram replays them forever.
                self._state.telegram_offset = int(update.get("update_id", 0)) + 1
                try:
                    await self._handle_update(update)
                except Exception:  # noqa: BLE001
                    log.exception("Failed to handle update %s", update.get("update_id"))

            self._state.save()
        log.info("Telegram channel monitor stopped.")

    async def _handle_update(self, update: dict) -> None:
        post = (
            update.get("channel_post")
            or update.get("edited_channel_post")
            or update.get("message")
        )
        if not post:
            return

        chat = post.get("chat", {})
        if not self._is_watched(chat):
            return

        text = post.get("text") or post.get("caption") or ""
        if not text.strip():
            return

        key = f"tg:{chat.get('id')}:{post.get('message_id')}"
        if not self._state.is_new(key):
            return
        self._state.mark_seen(key)

        matches = self._config.matcher.find_all(text)
        if not matches:
            return

        username = chat.get("username")
        source = f"@{username}" if username else (chat.get("title") or str(chat.get("id")))
        url = (
            f"https://t.me/{username}/{post.get('message_id')}"
            if username and post.get("message_id")
            else None
        )

        alert = Alert(
            source=source,
            source_kind="telegram",
            title=chat.get("title") or source,
            body=text,
            matches=matches,
            url=url,
            published_at=_post_datetime(post),
            dedupe_key=key,
        )
        await self._notifier.send_alert(alert)

    def _is_watched(self, chat: dict) -> bool:
        if not self._wanted:
            # No allow-list: accept channel posts, ignore DMs to the bot.
            return chat.get("type") == "channel"
        username = (chat.get("username") or "").lower()
        chat_id = str(chat.get("id", ""))
        title = (chat.get("title") or "").lower()
        return username in self._wanted or chat_id in self._wanted or title in self._wanted


def _post_datetime(post: dict) -> datetime | None:
    stamp = post.get("date")
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc)
    except (ValueError, OSError, TypeError):
        return None
