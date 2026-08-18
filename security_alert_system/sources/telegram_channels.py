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
GROUPS NEED PRIVACY MODE OFF
----------------------------
A bot added to a **group** sees nothing by default. Telegram's privacy mode
hides every message that is not a command or a reply to the bot, so the monitor
sits there matching zero keywords and looking broken. Fix it once, in BotFather:

    /setprivacy → pick the bot → Disable

then **remove and re-add the bot to the group** — the setting is applied when
the bot joins, so an existing membership keeps the old behaviour.

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
from typing import TYPE_CHECKING

from ..alerts import Alert
from ..config import Config
from ..monitoring import Runtime
from ..notifier import Notifier
from ..state import StateStore
from ..telegram_api import TelegramClient, TelegramError

if TYPE_CHECKING:  # avoids importing the anthropic SDK unless the assistant is used
    from ..assistant import SecurityAssistant
    from ..voice import Speaker, Transcriber

log = logging.getLogger(__name__)

ALLOWED_UPDATES = ["channel_post", "edited_channel_post", "message"]
# Health entry for the polling connection itself, distinct from any channel.
API_SOURCE = "Telegram Bot API"


class TelegramChannelMonitor:
    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        notifier: Notifier,
        state: StateStore,
        runtime: Runtime | None = None,
        assistant: "SecurityAssistant | None" = None,
        transcriber: "Transcriber | None" = None,
        speaker: "Speaker | None" = None,
    ):
        self._config = config
        self._client = client
        self._notifier = notifier
        self._state = state
        self._runtime = runtime
        self._assistant = assistant
        self._transcriber = transcriber
        self._speaker = speaker
        # Accept "@name", "name", or a numeric -100... id.
        self._wanted = {c.lstrip("@").lower() for c in config.telegram_channels}
        if runtime:
            runtime.source(API_SOURCE, "telegram")
            for channel in config.telegram_channels:
                runtime.source(channel, "telegram")

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
                if self._runtime:
                    self._runtime.source(API_SOURCE, "telegram").record_success(len(updates))
            except TelegramError as exc:
                log.error("getUpdates failed: %s (retrying in %.0fs)", exc, backoff)
                if self._runtime:
                    self._runtime.source(API_SOURCE, "telegram").record_error(str(exc))
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
        text = post.get("text") or post.get("caption") or ""

        # A private message from the owner is a question for the assistant,
        # not a channel post to filter for keywords.
        if chat.get("type") == "private":
            await self._handle_private_message(chat, post)
            return

        if not self._is_watched(chat):
            return
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
        if chat.get("type") in {"group", "supergroup"}:
            # In a group the author matters — "who said it" is part of judging
            # a report. Channels are broadcasts, so the channel name is enough.
            sender = post.get("from") or {}
            who = sender.get("username") or sender.get("first_name")
            if who:
                source = f"{source} · {who}"
        if self._runtime:
            self._runtime.source(source, "telegram").record_success(items=1)
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

    async def _handle_private_message(self, chat: dict, post: dict) -> None:
        """Route a DM to the assistant — but only from the configured chat.

        Anyone can find a bot and message it. Without this check a stranger
        could hold a conversation on the owner's API budget, and read back the
        alert history through the assistant's tools.
        """
        if str(chat.get("id")) != str(self._config.alert_chat_id):
            log.warning(
                "Ignoring private message from unauthorised chat %s.", chat.get("id")
            )
            return
        if not self._assistant:
            return

        # A voice note becomes text before anything else looks at it, so the
        # rest of this method cannot tell how the question arrived.
        spoken = bool(post.get("voice"))
        if spoken:
            text = await self._transcribe_voice(post["voice"])
            if not text:
                return
            log.info("Transcribed voice message: %s", text[:80])
        else:
            text = (post.get("text") or post.get("caption") or "").strip()
        if not text:
            return
        if text in {"/start", "/help"}:
            await self._notifier.send_notice(
                f"אני {self._config.assistant_name}. תשאל אותי על מצב המערכת, "
                "מה נקלט לאחרונה, או על מקור מסוים. /reset מנקה את השיחה."
            )
            return
        if text == "/reset":
            self._assistant.reset()
            await self._notifier.send_notice("השיחה אופסה.")
            return

        log.info("Assistant question: %s", text[:80])
        try:
            answer = await self._assistant.reply(text)
        except Exception:  # noqa: BLE001 - the assistant must never kill the loop
            log.exception("Assistant failed to answer.")
            return
        await self._deliver_answer(answer, spoken=spoken)

    async def _transcribe_voice(self, voice: dict) -> str:
        """Download a Telegram voice note and turn it into text."""
        if not self._transcriber:
            await self._notifier.send_notice(
                "קיבלתי הודעה קולית אבל תמלול לא מוגדר. תכתוב לי בטקסט."
            )
            return ""
        try:
            path = await self._client.get_file_path(voice["file_id"])
            audio = await self._client.download_file(path)
            return (await self._transcriber.transcribe(audio, "voice.ogg")).strip()
        except Exception:  # noqa: BLE001 - a bad clip must not kill the loop
            log.exception("Could not transcribe voice message.")
            await self._notifier.send_notice("לא הצלחתי לתמלל את ההודעה הקולית.")
            return ""

    async def _deliver_answer(self, answer: str, spoken: bool) -> None:
        """Answer in the medium the question arrived in.

        With headphones in a mall, a text reply is useless — and a voice reply
        to something typed at a desk is worse. "match" makes the round trip
        symmetric without him having to configure a mode per situation.
        """
        mode = self._config.voice_reply_mode
        want_voice = mode == "voice" or mode == "both" or (mode == "match" and spoken)
        want_text = mode == "text" or mode == "both" or (mode == "match" and not spoken)

        if want_voice and self._speaker:
            try:
                audio = await self._speaker.speak(answer)
            except Exception:  # noqa: BLE001
                log.exception("Speech synthesis failed; falling back to text.")
                audio = None
            if audio:
                try:
                    await self._client.send_voice(
                        self._config.alert_chat_id, audio, filename="reply.ogg"
                    )
                    if not want_text:
                        return
                except Exception:  # noqa: BLE001
                    log.exception("Could not send voice reply; falling back to text.")
            else:
                # Nothing was synthesised — the answer still has to arrive.
                want_text = True

        if want_text or not self._speaker:
            await self._notifier.send_plain(answer)

    # Channels broadcast; groups are conversations. Both are worth watching,
    # and both arrive here — but see the privacy-mode note in the module
    # docstring: in a group the bot sees nothing until you disable it.
    WATCHABLE_CHAT_TYPES = {"channel", "group", "supergroup"}

    def _is_watched(self, chat: dict) -> bool:
        if not self._wanted:
            # No allow-list: accept broadcast and group traffic, ignore DMs.
            return chat.get("type") in self.WATCHABLE_CHAT_TYPES
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
