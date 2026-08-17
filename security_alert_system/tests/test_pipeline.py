"""End-to-end tests: feed item -> keyword match -> rendered Telegram alert.

Uses a stub Telegram client, so no network and no bot token are needed.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import feedparser

from security_alert_system.alerts import Alert
from security_alert_system.cameras import (
    CameraRegistry,
    CameraStream,
    NullConnector,
    Snapshot,
)
from security_alert_system.config import Config
from security_alert_system.keywords import Severity
from security_alert_system.notifier import Notifier
from security_alert_system.sources.rss import RSSMonitor, strip_html
from security_alert_system.state import StateStore

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>חדשות לדוגמה</title>
  <item>
    <title>דיווח: פיגוע ירי בצומת</title>
    <link>https://example.com/1</link>
    <guid>item-1</guid>
    <description>&lt;p&gt;כוחות הביטחון סורקים את האזור.&lt;/p&gt;</description>
    <pubDate>Mon, 17 Aug 2026 08:00:00 +0300</pubDate>
  </item>
  <item>
    <title>מזג האוויר: התחממות קלה</title>
    <link>https://example.com/2</link>
    <guid>item-2</guid>
    <description>טמפרטורות ללא שינוי.</description>
    <pubDate>Mon, 17 Aug 2026 08:05:00 +0300</pubDate>
  </item>
</channel></rss>
"""


class StubTelegramClient:
    """Records what would have been sent."""

    def __init__(self):
        self.messages: list[str] = []
        self.photos: list[tuple[bytes, str]] = []

    async def send_message(self, chat_id, text, **_kwargs):
        self.messages.append(text)
        return {"message_id": len(self.messages)}

    async def send_photo(self, chat_id, image, caption="", **_kwargs):
        self.photos.append((image, caption))
        return {"message_id": len(self.photos)}


class AlwaysSnapshotConnector(NullConnector):
    name = "always"

    async def capture(self, stream: CameraStream) -> Snapshot:
        return Snapshot(stream.id, stream.name, b"\xff\xd8fake-jpeg")


def make_pieces(tmpdir: str, cameras: CameraRegistry | None = None):
    config = Config()
    config.rss_feeds = ["https://example.com/feed.xml"]
    config.state_path = Path(tmpdir) / "seen.json"
    state = StateStore(config.state_path)
    client = StubTelegramClient()
    notifier = Notifier(client, "42", cameras, Severity.CRITICAL)
    return config, state, client, notifier


class TestRSSPipeline(unittest.TestCase):
    def test_matching_item_alerts_and_others_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, state, client, notifier = make_pieces(tmp)
            monitor = RSSMonitor(config, notifier, state)
            parsed = feedparser.parse(FEED_XML)

            async def run():
                for entry in parsed.entries:
                    await monitor._handle_entry(
                        "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=True
                    )

            asyncio.run(run())

            self.assertEqual(len(client.messages), 1)
            body = client.messages[0]
            self.assertIn("פיגוע", body)
            self.assertIn("חדשות לדוגמה", body)
            self.assertIn("https://example.com/1", body)
            self.assertIn("קריטית", body)

    def test_same_item_is_not_alerted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, state, client, notifier = make_pieces(tmp)
            monitor = RSSMonitor(config, notifier, state)
            entry = feedparser.parse(FEED_XML).entries[0]

            async def run():
                for _ in range(3):
                    await monitor._handle_entry(
                        "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=True
                    )

            asyncio.run(run())
            self.assertEqual(len(client.messages), 1)

    def test_priming_records_without_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, state, client, notifier = make_pieces(tmp)
            monitor = RSSMonitor(config, notifier, state)
            entry = feedparser.parse(FEED_XML).entries[0]

            async def run():
                await monitor._handle_entry(
                    "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=False
                )
                # Second pass with alerting on: already seen, so still silent.
                await monitor._handle_entry(
                    "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=True
                )

            asyncio.run(run())
            self.assertEqual(client.messages, [])

    def test_dedupe_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, state, client, notifier = make_pieces(tmp)
            monitor = RSSMonitor(config, notifier, state)
            entry = feedparser.parse(FEED_XML).entries[0]

            asyncio.run(monitor._handle_entry(
                "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=True))
            state.save(force=True)

            reloaded = StateStore(config.state_path)
            monitor2 = RSSMonitor(config, notifier, reloaded)
            asyncio.run(monitor2._handle_entry(
                "https://example.com/feed.xml", "חדשות לדוגמה", entry, alerting=True))

            self.assertEqual(len(client.messages), 1)

    def test_strip_html(self):
        self.assertEqual(strip_html("<p>שלום<br/>עולם</p>"), "שלום\nעולם")
        self.assertEqual(strip_html("&quot;פיגוע&quot;"), '"פיגוע"')


class TestAlertRendering(unittest.TestCase):
    def test_html_is_escaped(self):
        from security_alert_system.keywords import KeywordMatcher

        matches = KeywordMatcher().find_all("פיגוע")
        alert = Alert(
            source="<b>evil</b>",
            source_kind="rss",
            title="פיגוע & <script>",
            body="פיגוע",
            matches=matches,
        )
        rendered = alert.to_html()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&amp;", rendered)

    def test_severity_is_highest_of_matches(self):
        from security_alert_system.keywords import KeywordMatcher

        matches = KeywordMatcher().find_all("אזעקה נשמעה, חשד לפיגוע")
        alert = Alert("s", "rss", "t", "b", matches)
        self.assertEqual(alert.severity, Severity.CRITICAL)


class TestCameraPlaceholder(unittest.TestCase):
    def test_disabled_registry_captures_nothing(self):
        registry = CameraRegistry(
            [CameraStream("cam1", "Gate", "rtsp://192.168.1.50/s")],
            NullConnector(),
            enabled=False,
        )
        self.assertEqual(asyncio.run(registry.capture_all()), [])

    def test_null_connector_returns_none_when_enabled(self):
        registry = CameraRegistry(
            [CameraStream("cam1", "Gate", "rtsp://192.168.1.50/s")],
            NullConnector(),
            enabled=True,
        )
        self.assertEqual(asyncio.run(registry.capture_all()), [])

    def test_credentials_are_stripped_from_logged_url(self):
        stream = CameraStream("cam1", "Gate", "rtsp://admin:hunter2@192.168.1.50:554/s")
        self.assertNotIn("hunter2", stream.safe_url)
        self.assertEqual(stream.safe_url, "rtsp://192.168.1.50:554/s")

    def test_snapshots_attach_to_critical_alerts_only(self):
        from security_alert_system.keywords import KeywordMatcher

        registry = CameraRegistry(
            [CameraStream("gate", "שער", "rtsp://x/y")],
            AlwaysSnapshotConnector(),
            enabled=True,
        )
        client = StubTelegramClient()
        notifier = Notifier(client, "42", registry, Severity.CRITICAL)
        matcher = KeywordMatcher()

        critical = Alert("s", "rss", "t", "b", matcher.find_all("פיגוע"))
        elevated = Alert("s", "rss", "t", "b", matcher.find_all("פיקוד העורף"))

        asyncio.run(notifier.send_alert(critical))
        self.assertEqual(len(client.photos), 1)

        asyncio.run(notifier.send_alert(elevated))
        self.assertEqual(len(client.photos), 1)  # unchanged

    def test_tag_filter(self):
        registry = CameraRegistry(
            [
                CameraStream("a", "A", "rtsp://x", tags=["outdoor"]),
                CameraStream("b", "B", "rtsp://y", tags=["indoor"]),
            ],
            AlwaysSnapshotConnector(),
            enabled=True,
        )
        snaps = asyncio.run(registry.capture_all(tag="outdoor"))
        self.assertEqual([s.camera_id for s in snaps], ["a"])


if __name__ == "__main__":
    unittest.main()
