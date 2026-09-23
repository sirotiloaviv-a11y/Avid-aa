"""End-to-end pipeline (candles → liquidity → urgency → notification) and configuration."""

from __future__ import annotations

import dataclasses
import unittest

from crypto_alerts.config import (
    ConfigError,
    ExchangeSettings,
    LiquiditySettings,
    RiskSettings,
    Settings,
    TelegramSettings,
    UrgentSettings,
)
from crypto_alerts.indicators import compute_indicators
from crypto_alerts.main import AlertEngine, Cooldown, build_channels
from crypto_alerts.market_data import MarketDataFeed
from crypto_alerts.risk_manager import RiskError, RiskManager
from crypto_alerts.state import RuntimeState
from crypto_alerts.strategy import Direction, RsiVolumeReversalStrategy

from .helpers import INDICATORS, STRATEGY, long_setup, make_book


class CapturingDispatcher:
    def __init__(self):
        self.messages = []

    def enqueue(self, notification):
        self.messages.append(notification)

    def snapshot(self):
        return {"queued": 0, "dropped": 0, "channels": {}}


class FakeFeed(MarketDataFeed):
    """Every candle is fresh, sizes round to 3 decimals, and the order book is scripted."""

    def __init__(self, settings, book=None, book_error=None):
        super().__init__(settings, exchange=object())
        self.book, self.book_error = book, book_error

    def is_stale(self, candle, now_ms=None):
        return False

    def round_amount(self, symbol, units):
        return int(units * 1000) / 1000

    async def fetch_order_book(self, symbol, limit=None):
        if self.book_error:
            raise self.book_error
        return self.book


def make_engine(book=None, book_error=None, **overrides):
    settings = Settings(
        exchange=ExchangeSettings(history_candles=50),
        indicators=INDICATORS,
        strategy=STRATEGY,
        risk=RiskSettings(account_equity=1_000_000, risk_per_trade_pct=0.5),
        **overrides,
    )
    dispatcher = CapturingDispatcher()
    engine = AlertEngine(
        settings,
        FakeFeed(settings.exchange, book if book is not None else make_book(100.0, 1e7), book_error),
        RsiVolumeReversalStrategy(settings.strategy),
        RiskManager(settings.risk),
        dispatcher,
        RuntimeState(["BTC/USDT"]),
    )
    return engine, dispatcher


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_produces_a_sized_alert(self):
        engine, dispatcher = make_engine()
        plan = await engine.process("BTC/USDT", long_setup())
        self.assertIsNotNone(plan)
        self.assertIs(plan.direction, Direction.LONG)
        self.assertLessEqual(plan.risk_amount, 5_000.0)
        self.assertGreater(plan.risk_amount, 4_990.0)  # only lot-step rounding below budget
        self.assertEqual(plan.liquidity_action, "ok")
        [note] = dispatcher.messages
        self.assertIn("🟢 <b>LONG</b>", note.text)
        self.assertIn("<b>SL</b>", note.short_text)
        self.assertFalse(note.urgent)  # the fixture has no conviction factors
        [record] = engine.state.alerts
        self.assertEqual(record.status, "sent")
        self.assertEqual(engine.state.symbols["BTC/USDT"].signals, 1)
        self.assertIsNotNone(engine.state.symbols["BTC/USDT"].rsi)

    async def test_cooldown_suppresses_repeat(self):
        engine, dispatcher = make_engine()
        await engine.process("BTC/USDT", long_setup())
        await engine.process("BTC/USDT", long_setup())
        self.assertEqual(len(dispatcher.messages), 1)
        self.assertEqual(engine.state.alerts[0].status, "suppressed")

    async def test_stale_candle_is_skipped(self):
        engine, dispatcher = make_engine()
        engine.feed.is_stale = lambda candle, now_ms=None: True
        self.assertIsNone(await engine.process("BTC/USDT", long_setup()))
        self.assertEqual(dispatcher.messages, [])

    async def test_thin_book_filtered(self):
        engine, dispatcher = make_engine(book=make_book(100.0, 10), liquidity=LiquiditySettings(action="filter"))
        self.assertIsNone(await engine.process("BTC/USDT", long_setup()))
        self.assertEqual(dispatcher.messages, [])
        self.assertEqual(engine.state.alerts[0].status, "filtered")

    async def test_thin_book_warned(self):
        engine, dispatcher = make_engine(book=make_book(100.0, 10))
        plan = await engine.process("BTC/USDT", long_setup())
        self.assertEqual(plan.liquidity_action, "warned")
        self.assertIn("THIN BOOK", dispatcher.messages[0].text)

    async def test_order_book_failure_still_alerts(self):
        engine, dispatcher = make_engine(book_error=ConnectionError("reset"))
        plan = await engine.process("BTC/USDT", long_setup())
        self.assertEqual(plan.liquidity_error, "ConnectionError")
        self.assertIn("Order book unavailable", dispatcher.messages[0].text)

    async def test_liquidity_check_can_be_disabled(self):
        engine, _ = make_engine(book_error=AssertionError("must not be called"),
                                liquidity=LiquiditySettings(enabled=False))
        plan = await engine.process("BTC/USDT", long_setup())
        self.assertEqual(plan.liquidity_action, "unchecked")

    async def test_urgent_when_enough_conviction_factors(self):
        engine, dispatcher = make_engine(urgent=UrgentSettings(min_factors=1))
        await engine.process("BTC/USDT", long_setup(signal_volume=600.0))  # extreme volume: 1 factor
        note = dispatcher.messages[0]
        self.assertTrue(note.urgent)
        self.assertIn("HIGH CONVICTION", note.text)
        self.assertTrue(note.title.startswith("🚨"))
        self.assertTrue(engine.state.alerts[0].urgent)


class UrgencyRuleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine, _ = make_engine(urgent=UrgentSettings(min_factors=2))
        signal = RsiVolumeReversalStrategy(STRATEGY).evaluate(
            "BTC/USDT", "15m", compute_indicators(long_setup(), INDICATORS))
        strong = dataclasses.replace(signal, conviction_factors=("a", "b"))
        self.plan = self.engine.risk.build_plan(strong)

    async def test_needs_factors_and_clean_liquidity(self):
        ok = dataclasses.replace(self.plan, liquidity_action="ok")
        self.assertTrue(self.engine.is_urgent(ok))
        self.assertTrue(self.engine.is_urgent(dataclasses.replace(ok, liquidity_action="reduced")))
        self.assertFalse(self.engine.is_urgent(dataclasses.replace(ok, liquidity_action="warned")))
        self.assertFalse(self.engine.is_urgent(dataclasses.replace(ok, liquidity_action="unchecked")))
        weak = dataclasses.replace(ok, signal=dataclasses.replace(ok.signal, conviction_factors=("a",)))
        self.assertFalse(self.engine.is_urgent(weak))


class RiskUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_applies_to_next_alert_and_is_announced(self):
        engine, dispatcher = make_engine()
        engine.update_risk(250_000, 1.0, source="test")
        plan = await engine.process("BTC/USDT", long_setup())
        self.assertAlmostEqual(plan.risk_budget, 2_500)
        self.assertLessEqual(plan.risk_amount, 2_500)
        announcement = dispatcher.messages[0]
        self.assertEqual(announcement.kind, "system")
        self.assertIn("$250,000.00", announcement.text)
        self.assertEqual(engine.state.risk_changes[0]["new"]["account_equity"], 250_000)

    async def test_no_op_update_is_silent(self):
        engine, dispatcher = make_engine()
        engine.update_risk(1_000_000, 0.5)
        self.assertEqual(dispatcher.messages, [])

    async def test_invalid_update_raises_and_changes_nothing(self):
        engine, _ = make_engine()
        with self.assertRaises(RiskError):
            engine.update_risk(-1, None)
        self.assertEqual(engine.risk.risk_budget, 5_000)


class CooldownTests(unittest.TestCase):
    def test_window_is_per_symbol_and_direction(self):
        cd = Cooldown(minutes=60)
        self.assertTrue(cd.allow("BTC", Direction.LONG, 0))
        self.assertFalse(cd.allow("BTC", Direction.LONG, 30 * 60_000))
        self.assertTrue(cd.allow("BTC", Direction.SHORT, 30 * 60_000))
        self.assertTrue(cd.allow("ETH", Direction.LONG, 30 * 60_000))
        self.assertTrue(cd.allow("BTC", Direction.LONG, 60 * 60_000))


class ChannelWiringTests(unittest.TestCase):
    def test_dry_run_uses_console_and_bell(self):
        names = [c.name for c in build_channels(Settings(telegram=TelegramSettings(dry_run=True)))]
        self.assertEqual(names, ["console", "sound"])

    def test_live_with_pushover_and_sound(self):
        settings = Settings(
            telegram=TelegramSettings(bot_token="t", chat_id="1"),
            urgent=UrgentSettings(pushover_token="a", pushover_user="u", sound_command="afplay x.aiff"),
        )
        self.assertEqual([c.name for c in build_channels(settings)], ["telegram", "pushover", "sound"])


BASE_ENV = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        s = Settings.from_env(BASE_ENV)
        self.assertEqual(s.risk.account_equity, 1_000_000)
        self.assertEqual(s.risk.risk_budget, 5_000)
        self.assertEqual(s.exchange.timeframe, "15m")
        self.assertEqual((s.liquidity.enabled, s.liquidity.action, s.liquidity.max_slippage_pct), (True, "warn", 0.1))
        self.assertEqual((s.dashboard.host, s.dashboard.port), ("127.0.0.1", 8765))
        self.assertFalse(s.urgent.pushover_enabled)

    def test_parses_values(self):
        s = Settings.from_env({
            **BASE_ENV,
            "ACCOUNT_EQUITY": "250_000",
            "RISK_PER_TRADE_PCT": "1%",
            "SYMBOLS": "BTC/USDT:USDT, ETH/USDT:USDT",
            "EXCHANGE_ID": "Bybit",
            "MARKET_TYPE": "swap",
            "LIQUIDITY_ACTION": "reduce",
            "MAX_SLIPPAGE_PCT": "0.05",
            "PUSHOVER_APP_TOKEN": "a", "PUSHOVER_USER_KEY": "u", "PUSHOVER_PRIORITY": "2",
            "TELEGRAM_URGENT_CHAT_ID": "-100123",
        })
        self.assertEqual(s.risk.risk_budget, 2_500)
        self.assertEqual(s.exchange.symbols, ("BTC/USDT:USDT", "ETH/USDT:USDT"))
        self.assertEqual(s.exchange.exchange_id, "bybit")
        self.assertEqual((s.liquidity.action, s.liquidity.max_slippage_pct), ("reduce", 0.05))
        self.assertTrue(s.urgent.pushover_enabled)
        self.assertEqual(s.urgent.pushover_priority, 2)
        self.assertEqual(s.telegram.urgent_chat_id, "-100123")

    def test_reports_every_error_at_once(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({"ACCOUNT_EQUITY": "lots", "STOP_MODE": "magic", "TIMEFRAME": "15x",
                               "LIQUIDITY_ACTION": "panic"})
        message = str(ctx.exception)
        for fragment in ["ACCOUNT_EQUITY", "STOP_MODE", "TIMEFRAME", "TELEGRAM_BOT_TOKEN",
                         "TELEGRAM_CHAT_ID", "LIQUIDITY_ACTION"]:
            self.assertIn(fragment, message)

    def test_dry_run_needs_no_telegram(self):
        self.assertTrue(Settings.from_env({"DRY_RUN": "true"}).telegram.dry_run)

    def test_risk_percentage_typo_is_rejected(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "RISK_PER_TRADE_PCT": "50"})

    def test_history_must_cover_indicators(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "HISTORY_CANDLES": "100"})  # slow EMA is 200

    def test_pushover_needs_both_keys(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({**BASE_ENV, "PUSHOVER_APP_TOKEN": "a"})
        self.assertIn("PUSHOVER_USER_KEY", str(ctx.exception))

    def test_public_dashboard_requires_token(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({**BASE_ENV, "DASHBOARD_HOST": "0.0.0.0"})
        self.assertIn("DASHBOARD_TOKEN", str(ctx.exception))
        s = Settings.from_env({**BASE_ENV, "DASHBOARD_HOST": "0.0.0.0", "DASHBOARD_TOKEN": "x" * 32})
        self.assertEqual(s.dashboard.host, "0.0.0.0")

    def test_secrets_are_not_in_repr(self):
        s = Settings.from_env({**BASE_ENV, "EXCHANGE_API_SECRET": "hunter2", "PUSHOVER_APP_TOKEN": "po-tok",
                               "PUSHOVER_USER_KEY": "po-user", "DASHBOARD_TOKEN": "dash-tok"})
        for secret in ["hunter2", "123:abc", "po-tok", "po-user", "dash-tok"]:
            self.assertNotIn(secret, repr(s))


if __name__ == "__main__":
    unittest.main()
