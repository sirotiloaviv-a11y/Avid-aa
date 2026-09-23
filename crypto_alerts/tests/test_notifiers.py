"""Pushover, sound and dispatcher tests. HTTP and subprocesses are stubbed or harmless."""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest import mock

from crypto_alerts.notifiers import (
    PUSHOVER_URL,
    AlertDispatcher,
    Notification,
    PushoverChannel,
    SoundChannel,
    html_to_text,
)


class RecordingPost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, url, fields):
        self.calls.append((url, fields))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class PushoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def no_sleep(_):
            return None

        patcher = mock.patch("crypto_alerts.notifiers.asyncio.sleep", new=no_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    def channel(self, post, **kwargs):
        return PushoverChannel("app-token", "user-key", post=post, **kwargs)

    async def test_urgent_only_by_default(self):
        ch = self.channel(RecordingPost([]))
        self.assertTrue(ch.accepts(Notification("x", urgent=True)))
        self.assertFalse(ch.accepts(Notification("x")))
        self.assertFalse(ch.accepts(Notification("x", urgent=True, kind="system")))
        self.assertTrue(self.channel(RecordingPost([]), urgent_only=False).accepts(Notification("x")))

    async def test_sends_priority_sound_and_short_text(self):
        post = RecordingPost([(200, '{"status":1}')])
        ch = self.channel(post, priority=1, sound="siren")
        note = Notification("<b>long</b> html", title="🚨 LONG BTC", short_text="<b>SL</b> 1", urgent=True)
        self.assertTrue(await ch.send(note))
        url, fields = post.calls[0]
        self.assertEqual(url, PUSHOVER_URL)
        self.assertEqual(fields["priority"], "1")
        self.assertEqual(fields["sound"], "siren")
        self.assertEqual(fields["message"], "<b>SL</b> 1")
        self.assertEqual(fields["html"], "1")
        self.assertNotIn("retry", fields)

    async def test_emergency_priority_sets_retry_and_expire(self):
        post = RecordingPost([(200, "{}")])
        await self.channel(post, priority=2).send(Notification("x", urgent=True))
        fields = post.calls[0][1]
        self.assertEqual((fields["priority"], fields["retry"], fields["expire"]), ("2", "60", "1800"))

    async def test_non_urgent_is_sent_at_normal_priority(self):
        post = RecordingPost([(200, "{}")])
        await self.channel(post, priority=2, urgent_only=False).send(Notification("x"))
        self.assertEqual(post.calls[0][1]["priority"], "0")

    async def test_message_is_truncated_to_limit(self):
        post = RecordingPost([(200, "{}")])
        await self.channel(post).send(Notification("x", short_text="a" * 5000, urgent=True))
        self.assertEqual(len(post.calls[0][1]["message"]), 1024)

    async def test_retries_server_errors_and_network_failures(self):
        post = RecordingPost([(500, ""), OSError("down"), (200, "{}")])
        self.assertTrue(await self.channel(post).send(Notification("x", urgent=True)))
        self.assertEqual(len(post.calls), 3)

    async def test_client_error_is_not_retried(self):
        post = RecordingPost([(400, '{"errors":["user key is invalid"]}')])
        self.assertFalse(await self.channel(post).send(Notification("x", urgent=True)))
        self.assertEqual(len(post.calls), 1)

    async def test_rate_limit_is_retried(self):
        post = RecordingPost([(429, ""), (200, "{}")])
        self.assertTrue(await self.channel(post).send(Notification("x", urgent=True)))


class SoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_command_without_shell(self):
        ch = SoundChannel(f'"{sys.executable}" -c "import sys; sys.exit(0)"')
        self.assertTrue(await ch.send(Notification("x", urgent=True)))

    async def test_failing_command_reports_failure(self):
        self.assertFalse(await SoundChannel(f'"{sys.executable}" -c "raise SystemExit(3)"').send(Notification("x")))

    async def test_missing_binary_reports_failure(self):
        self.assertFalse(await SoundChannel("/nonexistent/player sound.wav").send(Notification("x")))

    async def test_urgent_only_filter(self):
        ch = SoundChannel("")
        self.assertFalse(ch.accepts(Notification("x")))
        self.assertTrue(ch.accepts(Notification("x", urgent=True)))


class FakeChannel:
    def __init__(self, name, result=True, urgent_only=False, delay=0.0):
        self.name, self.result, self.urgent_only, self.delay = name, result, urgent_only, delay
        self.received = []

    def accepts(self, n):
        return n.urgent or not self.urgent_only

    async def send(self, n):
        await asyncio.sleep(self.delay)
        self.received.append(n)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_fans_out_by_urgency_and_isolates_failures(self):
        telegram = FakeChannel("telegram")
        pushover = FakeChannel("pushover", urgent_only=True)
        broken = FakeChannel("broken", result=RuntimeError("boom"))
        dispatcher = AlertDispatcher([telegram, pushover, broken])
        worker = asyncio.create_task(dispatcher.run())
        dispatcher.enqueue(Notification("normal"))
        dispatcher.enqueue(Notification("hot", urgent=True))
        await dispatcher.drain(timeout=2)
        worker.cancel()
        self.assertEqual([n.text for n in telegram.received], ["normal", "hot"])
        self.assertEqual([n.text for n in pushover.received], ["hot"])
        stats = dispatcher.snapshot()["channels"]
        self.assertEqual(stats["telegram"]["sent"], 2)
        self.assertEqual(stats["broken"]["failed"], 2)
        self.assertIn("boom", stats["broken"]["last_error"])

    async def test_channels_are_sent_concurrently(self):
        slow = [FakeChannel(f"c{i}", delay=0.2) for i in range(3)]
        dispatcher = AlertDispatcher(slow)
        worker = asyncio.create_task(dispatcher.run())
        loop = asyncio.get_running_loop()
        start = loop.time()
        dispatcher.enqueue(Notification("x"))
        await dispatcher.drain(timeout=2)
        worker.cancel()
        self.assertLess(loop.time() - start, 0.5)

    async def test_plain_string_is_a_system_message(self):
        dispatcher = AlertDispatcher([])
        dispatcher.enqueue("hello")
        self.assertEqual(dispatcher._queue.get_nowait().kind, "system")

    async def test_full_queue_drops_instead_of_blocking(self):
        dispatcher = AlertDispatcher([], maxsize=1)
        dispatcher.enqueue(Notification("a"))
        dispatcher.enqueue(Notification("b"))
        self.assertEqual(dispatcher.dropped, 1)


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags_and_unescapes(self):
        self.assertEqual(html_to_text("<b>RSI</b> &lt; 30 &amp; <i>volume</i>"), "RSI < 30 & volume")


if __name__ == "__main__":
    unittest.main()
