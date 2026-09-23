"""Formatting and Telegram delivery tests. The bot is a stub — no python-telegram-bot, no network."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta
from unittest import mock

from crypto_alerts.config import LiquiditySettings, RiskSettings
from crypto_alerts.notifiers import Notification
from crypto_alerts.risk_manager import RiskManager
from crypto_alerts.strategy import Direction
from crypto_alerts.telegram_bot import TelegramNotifier, format_alert, format_price, format_push

from .helpers import make_book
from .test_risk_manager import make_signal


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskSettings())
        self.plan = self.rm.build_plan(make_signal())

    def test_contains_every_field(self):
        text = format_alert(self.plan, 900_000)
        for fragment in [
            "🟢 <b>LONG</b>", "BTC/USDT", "Entry:", "Stop Loss:", "Take Profit:",
            "Risk/Reward:</b> 1 : 2.5", "$5,000.00", "0.50% of equity", "BTC</code>",
            "RSI oversold + 3.0x Volume Surge", "Trigger Reasons", "Candle closed",
            "(−3.40%)", "(+8.50%)",
        ]:
            self.assertIn(fragment, text)
        self.assertNotIn("HIGH CONVICTION", text)

    def test_short_header(self):
        plan = self.rm.build_plan(make_signal(Direction.SHORT, invalidation=103.0))
        self.assertIn("🔴 <b>SHORT</b>", format_alert(plan))

    def test_urgent_header_and_conviction(self):
        signal = dataclasses.replace(make_signal(), conviction_factors=("Extreme RSI (15.0)", "Extreme volume (6.0x)"))
        text = format_alert(self.rm.build_plan(signal), urgent=True)
        self.assertTrue(text.startswith("🚨🔥 <b>HIGH CONVICTION</b>"))
        self.assertIn("Extreme volume (6.0x)", text)

    def test_html_is_escaped(self):
        signal = dataclasses.replace(make_signal(), reasons=("<script>&",))
        self.assertIn("&lt;script&gt;&amp;", format_alert(self.rm.build_plan(signal)))

    def test_leverage_cap_warning(self):
        rm = RiskManager(RiskSettings(max_leverage=0.1))
        self.assertIn("capped by MAX_LEVERAGE", format_alert(rm.build_plan(make_signal())))

    def test_liquidity_ok_line(self):
        plan = self.rm.apply_liquidity(self.plan, make_book(100.0, depth_units=1e6), LiquiditySettings())
        self.assertIn("Liquidity:</b> ✅", format_alert(plan))

    def test_thin_book_warning(self):
        plan = self.rm.apply_liquidity(self.plan, make_book(100.0, depth_units=100), LiquiditySettings())
        text = format_alert(plan)
        self.assertIn("THIN BOOK", text)
        self.assertIn("max size within limit", text)

    def test_reduced_size_line(self):
        plan = self.rm.apply_liquidity(self.plan, make_book(100.0, depth_units=100),
                                       LiquiditySettings(action="reduce"))
        self.assertIn("size reduced from", format_alert(plan))
        self.assertIn("Size reduced for liquidity", format_push(plan))

    def test_unavailable_book_is_flagged(self):
        plan = dataclasses.replace(self.plan, liquidity_error="NetworkError")
        self.assertIn("Order book unavailable", format_alert(plan))

    def test_push_text_fits_pushover(self):
        text = format_push(self.plan)
        self.assertLess(len(text), 1024)
        self.assertIn("<b>SL</b>", text)
        self.assertNotIn("<code>", text)  # Pushover does not render <code>

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
    def __init__(self, errors=()):
        self.errors = list(errors)
        self.sent = []

    async def send_message(self, **kwargs):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(kwargs)


class TelegramNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sleeps = []

        async def fake_sleep(delay):
            self.sleeps.append(delay)

        patcher = mock.patch("crypto_alerts.telegram_bot.asyncio.sleep", new=fake_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_retries_transient_errors_and_honours_retry_after(self):
        bot = StubBot([NetworkError("down"), RetryAfter(7)])
        self.assertTrue(await TelegramNotifier("t", "42", bot=bot).send(Notification("hi")))
        self.assertEqual(self.sleeps, [1.0, 7.0])
        self.assertEqual(bot.sent[0]["chat_id"], "42")
        self.assertEqual(bot.sent[0]["parse_mode"], "HTML")

    async def test_permanent_error_is_not_retried(self):
        bot = StubBot([BadRequest("can't parse entities")])
        self.assertFalse(await TelegramNotifier("t", "42", bot=bot).send(Notification("hi")))
        self.assertEqual(self.sleeps, [])

    async def test_gives_up_after_max_attempts(self):
        bot = StubBot([NetworkError()] * 10)
        self.assertFalse(await TelegramNotifier("t", "42", bot=bot, max_attempts=3).send(Notification("hi")))
        self.assertEqual(len(self.sleeps), 2)

    async def test_urgent_alert_is_copied_to_urgent_chat(self):
        bot = StubBot()
        notifier = TelegramNotifier("t", "main", urgent_chat_id="urgent", bot=bot)
        await notifier.send(Notification("normal"))
        await notifier.send(Notification("hot", urgent=True))
        self.assertEqual([(m["chat_id"], m["text"]) for m in bot.sent],
                         [("main", "normal"), ("main", "hot"), ("urgent", "hot")])

    async def test_quiet_mode_silences_only_normal_alerts(self):
        bot = StubBot()
        notifier = TelegramNotifier("t", "main", quiet_normal_alerts=True, bot=bot)
        await notifier.send(Notification("normal"))
        await notifier.send(Notification("hot", urgent=True))
        await notifier.send(Notification("startup", kind="system"))
        self.assertEqual([m["disable_notification"] for m in bot.sent], [True, False, False])


if __name__ == "__main__":
    unittest.main()
