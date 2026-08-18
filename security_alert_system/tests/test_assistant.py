"""Tests for the AI assistant layer.

The Anthropic client is stubbed, so these run with no API key and no network.
What they cover is the part this project owns: the tools' return values, the
conversation history, the failure paths, and — most importantly — the routing
rule that only the owner's chat reaches the model.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from security_alert_system.alerts import Alert
from security_alert_system.assistant import SecurityAssistant, severity_at_least
from security_alert_system.config import Config
from security_alert_system.keywords import KeywordMatcher, Severity
from security_alert_system.monitoring import Runtime
from security_alert_system.notifier import Notifier
from security_alert_system.sources.telegram_channels import TelegramChannelMonitor
from security_alert_system.state import StateStore


class StubRunner:
    """Stands in for BetaAsyncToolRunner."""

    def __init__(self, message, on_run=None):
        self._message = message
        self._on_run = on_run

    async def until_done(self):
        if isinstance(self._message, Exception):
            raise self._message
        if self._on_run:
            self._on_run()
        return self._message


class StubAnthropic:
    """Records the kwargs each call was made with, returns a canned reply."""

    def __init__(self, reply="בסדר.", error=None):
        self.calls: list[dict] = []
        self._reply = reply
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._runner))

    def _runner(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            return StubRunner(self._error)
        message = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="internal"),
                SimpleNamespace(type="text", text=self._reply),
            ]
        )
        return StubRunner(message)

    @property
    def tools(self) -> dict:
        """The tool objects from the most recent call, keyed by name."""
        return {t.name: t for t in self.calls[-1]["tools"]}


def make_assistant(reply="בסדר.", error=None, **config_overrides):
    config = Config()
    config.assistant_enabled = True
    config.anthropic_api_key = "test-key"
    config.alert_chat_id = "42"
    for key, value in config_overrides.items():
        setattr(config, key, value)

    runtime = Runtime(history_size=50)
    client = StubAnthropic(reply=reply, error=error)
    return SecurityAssistant(config, runtime, client=client), runtime, client


def make_alert(text="פיגוע ירי", source="ynet") -> Alert:
    return Alert(
        source=source,
        source_kind="rss",
        title=text,
        body=text,
        matches=KeywordMatcher().find_all(text),
    )


class TestAssistantReplies(unittest.TestCase):
    def test_reply_returns_text_and_keeps_history(self):
        assistant, _, client = make_assistant(reply="שקט בשעה האחרונה.")

        first = asyncio.run(assistant.reply("מה המצב?"))
        self.assertEqual(first, "שקט בשעה האחרונה.")

        asyncio.run(assistant.reply("ומה לפני זה?"))
        # Second call carries the first exchange plus the new question.
        messages = client.calls[-1]["messages"]
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["content"], "מה המצב?")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[2]["content"], "ומה לפני זה?")

    def test_thinking_blocks_are_not_sent_to_the_user(self):
        assistant, _, _ = make_assistant(reply="תשובה")
        self.assertEqual(asyncio.run(assistant.reply("שאלה")), "תשובה")

    def test_request_uses_configured_model_and_effort(self):
        assistant, _, client = make_assistant(
            assistant_model="claude-opus-5", assistant_effort="low"
        )
        asyncio.run(assistant.reply("מה המצב?"))
        call = client.calls[-1]
        self.assertEqual(call["model"], "claude-opus-5")
        self.assertEqual(call["output_config"], {"effort": "low"})
        self.assertEqual(call["thinking"], {"type": "adaptive"})
        self.assertIn("max_iterations", call)

    def test_history_is_bounded(self):
        assistant, _, client = make_assistant(assistant_history_turns=2)
        for i in range(6):
            asyncio.run(assistant.reply(f"שאלה {i}"))
        # 2 turns = 4 messages, and the newest question is always last.
        messages = client.calls[-1]["messages"]
        self.assertLessEqual(len(messages), 4)
        self.assertEqual(messages[-1]["content"], "שאלה 5")

    def test_reset_clears_history(self):
        assistant, _, client = make_assistant()
        asyncio.run(assistant.reply("ראשונה"))
        assistant.reset()
        asyncio.run(assistant.reply("שנייה"))
        self.assertEqual(len(client.calls[-1]["messages"]), 1)

    def test_api_failure_returns_a_message_and_drops_the_turn(self):
        from anthropic import APIConnectionError

        assistant, _, client = make_assistant(
            error=APIConnectionError(request=SimpleNamespace())
        )
        with self.assertLogs("security_alert_system.assistant", "ERROR"):
            answer = asyncio.run(assistant.reply("מה המצב?"))
        self.assertIn("לא הצלחתי", answer)
        # The unanswered question must not poison the next request.
        self.assertEqual(len(assistant._history), 0)

    def test_empty_response_is_handled(self):
        assistant, _, _ = make_assistant(reply="")
        answer = asyncio.run(assistant.reply("שאלה"))
        self.assertIn("לא קיבלתי תשובה", answer)


class TestAssistantTools(unittest.TestCase):
    """The tools are what keep answers grounded — check what they return."""

    def setUp(self):
        self.assistant, self.runtime, self.client = make_assistant()
        self.runtime.source("ynet", "rss").record_success(items=12)
        self.runtime.source("mako", "rss").record_error("HTTP 503")
        self.runtime.record_alert(make_alert("פיגוע דקירה בצומת"), delivered=True)
        self.runtime.record_alert(
            make_alert("אזעקות במרכז", source="@channel"), delivered=True
        )
        asyncio.run(self.assistant.reply("שאלה"))  # populates client.tools

    def _call(self, name, **kwargs) -> str:
        return asyncio.run(self.client.tools[name].call(kwargs))

    def test_tools_are_registered(self):
        self.assertEqual(
            set(self.client.tools),
            {"get_status", "recent_alerts", "search_alerts",
             "list_keywords", "camera_status"},
        )

    def test_get_status_reports_sources_and_counts(self):
        out = self._call("get_status")
        self.assertIn("ynet", out)
        self.assertIn("mako", out)
        self.assertIn("HTTP 503", out)
        self.assertIn("degraded", out)

    def test_recent_alerts_newest_first(self):
        out = self._call("recent_alerts", limit=5)
        self.assertLess(out.index("אזעקות במרכז"), out.index("פיגוע דקירה"))

    def test_recent_alerts_filters_by_severity(self):
        out = self._call("recent_alerts", limit=10, severity="ELEVATED")
        self.assertIn("לא נמצאו", out)

    def test_search_alerts_matches_title_source_and_phrase(self):
        self.assertIn("פיגוע דקירה", self._call("search_alerts", query="דקירה"))
        self.assertIn("אזעקות במרכז", self._call("search_alerts", query="@channel"))
        # "אזעקה" is a matched phrase on that alert but is NOT a substring of
        # its title ("אזעקות"), so this reaches only via the phrase list.
        self.assertIn("אזעקות במרכז", self._call("search_alerts", query="אזעקה"))

    def test_search_reports_absence_rather_than_nothing(self):
        # An empty result must still be a sentence — the model needs something
        # concrete to report instead of filling the silence.
        out = self._call("search_alerts", query="רחפן")
        self.assertIn("אין התראות", out)

    def test_list_keywords_groups_by_severity(self):
        out = self._call("list_keywords", severity="CRITICAL")
        self.assertIn("CRITICAL", out)
        self.assertIn("צבע אדום", out)
        self.assertNotIn("HIGH", out)

    def test_camera_status_reflects_config(self):
        self.assertIn("מושבתות", self._call("camera_status"))


class TestProactiveBrief(unittest.TestCase):
    def test_brief_returns_text(self):
        assistant, _, _ = make_assistant(reply="שלישית הערב מאותו אזור.")
        self.assertEqual(
            asyncio.run(assistant.brief(make_alert())), "שלישית הערב מאותו אזור."
        )

    def test_brief_suppressed_when_nothing_to_add(self):
        assistant, _, _ = make_assistant(reply="אין הקשר נוסף")
        self.assertIsNone(asyncio.run(assistant.brief(make_alert())))

    def test_brief_is_not_added_to_conversation_history(self):
        assistant, _, client = make_assistant(reply="הקשר.")
        asyncio.run(assistant.brief(make_alert()))
        asyncio.run(assistant.reply("מה המצב?"))
        self.assertEqual(len(client.calls[-1]["messages"]), 1)

    def test_brief_failure_returns_none(self):
        from anthropic import APIConnectionError

        assistant, _, _ = make_assistant(
            error=APIConnectionError(request=SimpleNamespace())
        )
        with self.assertLogs("security_alert_system.assistant", "WARNING"):
            self.assertIsNone(asyncio.run(assistant.brief(make_alert())))


class StubTelegramClient:
    def __init__(self):
        self.messages: list[str] = []

    async def send_message(self, chat_id, text, **_kwargs):
        self.messages.append(text)
        return {"message_id": len(self.messages)}

    async def send_photo(self, *a, **k):
        return {}


class TestNotifierBriefing(unittest.IsolatedAsyncioTestCase):
    async def test_brief_follows_a_critical_alert(self):
        assistant, _, _ = make_assistant(reply="דפוס חוזר.")
        client = StubTelegramClient()
        notifier = Notifier(
            client, "42", assistant=assistant, brief_threshold=Severity.CRITICAL
        )
        await notifier.send_alert(make_alert("פיגוע"))

        self.assertEqual(len(client.messages), 2)
        self.assertIn("פיגוע", client.messages[0])   # the alert itself, first
        self.assertIn("דפוס חוזר", client.messages[1])

    async def test_no_brief_below_threshold(self):
        assistant, _, _ = make_assistant(reply="הערה.")
        client = StubTelegramClient()
        notifier = Notifier(
            client, "42", assistant=assistant, brief_threshold=Severity.CRITICAL
        )
        await notifier.send_alert(make_alert("פיקוד העורף"))  # ELEVATED
        self.assertEqual(len(client.messages), 1)

    async def test_alert_still_lands_when_the_brief_fails(self):
        from anthropic import APIConnectionError

        assistant, _, _ = make_assistant(
            error=APIConnectionError(request=SimpleNamespace())
        )
        client = StubTelegramClient()
        notifier = Notifier(
            client, "42", assistant=assistant, brief_threshold=Severity.CRITICAL
        )
        with self.assertLogs("security_alert_system.assistant", "WARNING"):
            ok = await notifier.send_alert(make_alert("פיגוע"))
        self.assertTrue(ok)
        self.assertEqual(len(client.messages), 1)

    async def test_model_output_is_html_escaped(self):
        # A bare "<" in model output is rejected by Telegram's HTML parser —
        # escaping is what makes the message arrive at all.
        assistant, _, _ = make_assistant(reply="ירידה <5% בתעבורה & עוד")
        client = StubTelegramClient()
        notifier = Notifier(
            client, "42", assistant=assistant, brief_threshold=Severity.CRITICAL
        )
        await notifier.send_alert(make_alert("פיגוע"))
        self.assertIn("&lt;5%", client.messages[1])
        self.assertIn("&amp;", client.messages[1])


class TestPrivateMessageRouting(unittest.IsolatedAsyncioTestCase):
    """The access check: only the configured chat may talk to the model."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.assistant, _, self.client = make_assistant(reply="הכול תקין.")
        self.config = self.assistant._config
        self.config.bot_token = "t"
        self.telegram = StubTelegramClient()
        self.notifier = Notifier(self.telegram, "42")
        self.monitor = TelegramChannelMonitor(
            self.config,
            self.telegram,
            self.notifier,
            StateStore(Path(self.tmp.name) / "seen.json"),
            assistant=self.assistant,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _dm(self, chat_id: str, text: str) -> dict:
        return {
            "update_id": 1,
            "message": {
                "message_id": 7,
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
                "date": 1,
            },
        }

    async def test_owner_message_reaches_the_assistant(self):
        await self.monitor._handle_update(self._dm("42", "מה המצב?"))
        self.assertEqual(len(self.client.calls), 1)
        self.assertIn("הכול תקין", self.telegram.messages[-1])

    async def test_stranger_message_is_ignored(self):
        with self.assertLogs(
            "security_alert_system.sources.telegram_channels", "WARNING"
        ):
            await self.monitor._handle_update(self._dm("999", "מה המצב?"))
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.telegram.messages, [])

    async def test_reset_command_clears_history_without_calling_the_model(self):
        await self.monitor._handle_update(self._dm("42", "שאלה"))
        await self.monitor._handle_update(self._dm("42", "/reset"))
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(len(self.assistant._history), 0)

    async def test_help_command_does_not_call_the_model(self):
        await self.monitor._handle_update(self._dm("42", "/start"))
        self.assertEqual(self.client.calls, [])
        self.assertIn(self.config.assistant_name, self.telegram.messages[-1])

    async def test_private_message_is_not_keyword_filtered(self):
        # A DM mentioning a keyword is a question, not a channel post to alert on.
        await self.monitor._handle_update(self._dm("42", "היה פיגוע היום?"))
        self.assertEqual(len(self.client.calls), 1)
        self.assertNotIn("התראה", self.telegram.messages[-1])


class TestSeverityHelper(unittest.TestCase):
    def test_at_least(self):
        self.assertTrue(severity_at_least("CRITICAL", Severity.HIGH))
        self.assertTrue(severity_at_least("high", Severity.HIGH))
        self.assertFalse(severity_at_least("ELEVATED", Severity.HIGH))
        self.assertFalse(severity_at_least("nonsense", Severity.HIGH))


if __name__ == "__main__":
    unittest.main()
