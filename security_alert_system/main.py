"""Entry point.

    python -m security_alert_system.main            # run the monitor
    python -m security_alert_system.main --test     # send a test alert and exit
    python -m security_alert_system.main --check    # validate config and exit
    python -m security_alert_system.main --chat-id  # discover your chat id
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from .alerts import Alert
from .cameras import CameraRegistry
from .config import BASE_DIR, Config
from .keywords import Match, Severity
from .notifier import Notifier
from .sources import RSSMonitor, TelegramChannelMonitor
from .state import StateStore
from .telegram_api import TelegramClient, TelegramError

log = logging.getLogger("security_alert_system")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            # Not available on every platform / non-main thread.
            pass


async def run_monitor(config: Config) -> int:
    problems = config.validate()
    if problems:
        for problem in problems:
            log.error("Config: %s", problem)
        return 1

    state = StateStore(config.state_path, config.state_max_entries)
    cameras = CameraRegistry.from_env(BASE_DIR)
    threshold = getattr(Severity, config.camera_snapshot_on_severity, Severity.CRITICAL)

    stop = asyncio.Event()
    install_signal_handlers(stop)

    async with TelegramClient(config.bot_token, config.http_timeout_seconds) as client:
        try:
            me = await client.get_me()
        except TelegramError as exc:
            log.error("Cannot reach Telegram with this token: %s", exc)
            return 1
        log.info("Connected as @%s (%s).", me.get("username"), me.get("id"))

        notifier = Notifier(client, config.alert_chat_id, cameras, threshold)

        log.info("Watching %d RSS feed(s): %s", len(config.rss_feeds),
                 ", ".join(config.rss_feeds))
        log.info("Watching %d Telegram channel(s): %s",
                 len(config.telegram_channels),
                 ", ".join(config.telegram_channels) or "none")
        log.info("Keywords: %s", ", ".join(r.phrase for r in config.matcher.rules))
        log.info("%s", cameras.describe())
        log.info("%s", await cameras.connector.healthcheck())

        await notifier.send_notice(
            "🟢 <b>מערכת ההתראות עלתה</b>\n"
            f"📰 פידים: {len(config.rss_feeds)} | "
            f"📢 ערוצים: {len(config.telegram_channels)} | "
            f"🔑 מילות מפתח: {len(config.matcher.rules)}"
        )

        rss = RSSMonitor(config, notifier, state)
        telegram = TelegramChannelMonitor(config, client, notifier, state)

        tasks = [
            asyncio.create_task(rss.run(stop), name="rss"),
            asyncio.create_task(telegram.run(stop), name="telegram"),
        ]
        try:
            await stop.wait()
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            state.save(force=True)
            log.info("Shut down cleanly.")
    return 0


async def send_test_alert(config: Config) -> int:
    if not config.bot_token or not config.alert_chat_id:
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID must both be set.")
        return 1

    sample = "התקבל דיווח על אירוע ביטחוני באזור; כוחות הביטחון סורקים את השטח."
    matches: list[Match] = config.matcher.find_all(sample)
    async with TelegramClient(config.bot_token, config.http_timeout_seconds) as client:
        notifier = Notifier(client, config.alert_chat_id)
        alert = Alert(
            source="בדיקה מקומית",
            source_kind="rss",
            title="הודעת בדיקה — המערכת פועלת",
            body=sample,
            matches=matches,
            url="https://example.com/test",
            published_at=datetime.now(timezone.utc),
        )
        ok = await notifier.send_alert(alert)
    if ok:
        log.info("Test alert delivered. Matched: %s",
                 ", ".join(m.phrase for m in matches) or "nothing")
    return 0 if ok else 1


async def show_chat_id(config: Config) -> int:
    """Print the chat ids the bot can currently see, to fill in ALERT_CHAT_ID."""
    if not config.bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set.")
        return 1
    async with TelegramClient(config.bot_token, config.http_timeout_seconds) as client:
        me = await client.get_me()
        print(f"Bot: @{me.get('username')}")
        print("Send any message to your bot (or post in the channel), then re-run this.\n")
        updates = await client.get_updates(long_poll_seconds=10)
        if not updates:
            print("No updates received. Message the bot in a private chat and try again.")
            return 0
        seen: set[str] = set()
        for update in updates:
            post = (update.get("message") or update.get("channel_post")
                    or update.get("edited_channel_post") or {})
            chat = post.get("chat") or {}
            if not chat or str(chat.get("id")) in seen:
                continue
            seen.add(str(chat.get("id")))
            label = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
            print(f"  id={chat.get('id')}  type={chat.get('type')}  {label}")
    return 0


def check_config(config: Config) -> int:
    problems = config.validate()
    print(f"RSS feeds ({len(config.rss_feeds)}):")
    for feed in config.rss_feeds:
        print(f"  - {feed}")
    print(f"Telegram channels ({len(config.telegram_channels)}):")
    for channel in config.telegram_channels:
        print(f"  - {channel}")
    print(f"Keywords ({len(config.matcher.rules)}):")
    for rule in config.matcher.rules:
        print(f"  - {rule.phrase}  [{rule.severity.name}]")
    print(f"State file: {config.state_path}")
    print(CameraRegistry.from_env(BASE_DIR).describe())
    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("\nConfiguration looks OK.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hebrew security alert monitor")
    parser.add_argument("--test", action="store_true", help="send one test alert and exit")
    parser.add_argument("--check", action="store_true", help="print config and exit")
    parser.add_argument("--chat-id", action="store_true", help="discover your chat id")
    args = parser.parse_args()

    config = Config.from_env()
    setup_logging(config.log_level)

    if args.check:
        return check_config(config)
    if args.chat_id:
        return asyncio.run(show_chat_id(config))
    if args.test:
        return asyncio.run(send_test_alert(config))
    return asyncio.run(run_monitor(config))


if __name__ == "__main__":
    raise SystemExit(main())
