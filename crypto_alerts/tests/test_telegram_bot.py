"""Formatting and delivery tests. The bot is a stub — no python-telegram-bot, no network."""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from unittest import mock

from crypto_alerts.config import RiskSettings
from crypto_alerts.risk_manager import RiskManager
from crypto_alerts.strategy import Direction
from crypto_alerts.telegram_bot import (
    AlertDispatcher,
    TelegramNotifier,
    format_alert,
    format_price,
)

from .test_risk_manager import make_signal


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.plan = RiskManager(RiskSettings()).build_plan(make_signal())

    def test_contains_every_field(self):
        text = format_alert(self.plan, 900_000)
        for fragment in [
            "🟢 <b>LONG</b>", "BTC/USDT", "Entry:", "Stop Loss:", "Take Profit:",
            "Risk/Reward:</b> 1 : 2.5", "$5,000.00", "0.50% of equity", "BTC</code>",
            "RSI oversold + 3.0x Volume Surge", "Trigger Reasons", "Candle closed",
            "(−3.40%)", "(+8.50%)",
        ]:
            self.assertIn(fragment, text)

    def test_short_header(self):
        plan = RiskManager(RiskSettings()).build_plan(make_signal(Direction.SHORT, invalidation=103.0))
        self.assertIn("🔴 <b>SHORT</b>", format_alert(plan))

    def test_html_is_escaped(self):
        signal = make_signal()
        object.__setattr__(signal, "reasons", ("<script>&",))
        plan = RiskManager(RiskSettings()).build_plan(signal)
        self.assertIn("&lt;script&gt;&amp;", format_alert(plan))

    def test_leverage_cap_warning(self):
        rm = RiskManager(RiskSettings(max_leverage=0.1))
        self.assertIn("capped by MAX_LEVERAGE", format_alert(rm.build_plan(make_signal())))

    def test_price_formatting_scales(self):
        self.assertEqual(format_price(64123.456), "64,123.46")
        self.assertEqual(format_price(142.5), "142.5000")
        self.assertEqual(format_price(0.5123), "0.5123")
        self.assertEqual(format_price(0.00001234), "0.00001234")


class NetworkError(Exception):
    pass


class RetryAfter(Exception):
    def __init__(self, seconds):
        super().__init__("flood")
        self.retry_after = timedelta(seconds=seconds)


class BadRequest(Exception):
    pass


class StubBot:
    def __init__(self, errors):
        self.errors = list(errors)
        self.sent = []

    async def send_message(self, **kwargs):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(kwargs)


class NotifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sleeps = []

        async def fake_sleep(delay):
            self.sleeps.append(delay)

        patcher = mock.patch("crypto_alerts.telegram_bot.asyncio.sleep", new=fake_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_retries_transient_errors_and_honours_retry_after(self):
        bot = StubBot([NetworkError("down"), RetryAfter(7)])
        notifier = TelegramNotifier("t", "42", bot=bot)
        self.assertTrue(await notifier.send("hi"))
        self.assertEqual(self.sleeps, [1.0, 7.0])
        self.assertEqual(bot.sent[0]["chat_id"], "42")
        self.assertEqual(bot.sent[0]["parse_mode"], "HTML")

    async def test_permanent_error_is_not_retried(self):
        bot = StubBot([BadRequest("can't parse entities")])
        self.assertFalse(await TelegramNotifier("t", "42", bot=bot).send("hi"))
        self.assertEqual(self.sleeps, [])

    async def test_gives_up_after_max_attempts(self):
        bot = StubBot([NetworkError()] * 10)
        self.assertFalse(await TelegramNotifier("t", "42", bot=bot, max_attempts=3).send("hi"))
        self.assertEqual(len(self.sleeps), 2)


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivers_queued_alerts(self):
        bot = StubBot([])
        dispatcher = AlertDispatcher(TelegramNotifier("t", "1", bot=bot))
        worker = asyncio.create_task(dispatcher.run())
        dispatcher.enqueue("a")
        dispatcher.enqueue("b")
        await dispatcher.drain(timeout=2)
        worker.cancel()
        self.assertEqual([m["text"] for m in bot.sent], ["a", "b"])
        self.assertEqual(dispatcher.sent, 2)

    async def test_full_queue_drops_instead_of_blocking(self):
        dispatcher = AlertDispatcher(TelegramNotifier("t", "1", bot=StubBot([])), maxsize=1)
        dispatcher.enqueue("a")
        dispatcher.enqueue("b")  # must not raise or block
        self.assertEqual(dispatcher._queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
