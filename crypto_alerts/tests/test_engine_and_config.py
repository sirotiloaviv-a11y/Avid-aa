"""End-to-end pipeline (candles → alert text) and configuration loading."""

from __future__ import annotations

import dataclasses
import unittest

from crypto_alerts.config import ConfigError, ExchangeSettings, RiskSettings, Settings
from crypto_alerts.main import AlertEngine, Cooldown
from crypto_alerts.market_data import MarketDataFeed
from crypto_alerts.risk_manager import RiskManager
from crypto_alerts.strategy import Direction, RsiVolumeReversalStrategy

from .helpers import INDICATORS, STRATEGY, TF_MS, long_setup


class CapturingDispatcher:
    def __init__(self):
        self.messages = []

    def enqueue(self, text):
        self.messages.append(text)


class FreshFeed(MarketDataFeed):
    """Treats every candle as just closed and rounds to 3 decimals."""

    def is_stale(self, candle, now_ms=None):
        return False

    def round_amount(self, symbol, units):
        return int(units * 1000) / 1000


def make_engine(**settings_overrides):
    settings = Settings(
        exchange=ExchangeSettings(history_candles=50),
        indicators=INDICATORS,
        strategy=STRATEGY,
        risk=RiskSettings(account_equity=1_000_000, risk_per_trade_pct=0.5),
        **settings_overrides,
    )
    dispatcher = CapturingDispatcher()
    engine = AlertEngine(
        settings,
        FreshFeed(settings.exchange, exchange=object()),
        RsiVolumeReversalStrategy(settings.strategy),
        RiskManager(settings.risk),
        dispatcher,
    )
    return engine, dispatcher


class EngineTests(unittest.TestCase):
    def test_setup_produces_a_sized_alert(self):
        engine, dispatcher = make_engine()
        plan = engine.process("BTC/USDT", long_setup())
        self.assertIsNotNone(plan)
        self.assertIs(plan.direction, Direction.LONG)
        self.assertLessEqual(plan.risk_amount, 5_000.0)
        self.assertGreater(plan.risk_amount, 4_990.0)  # only lot-step rounding below budget
        self.assertEqual(len(dispatcher.messages), 1)
        self.assertIn("🟢 <b>LONG</b>", dispatcher.messages[0])

    def test_cooldown_suppresses_repeat(self):
        engine, dispatcher = make_engine()
        engine.process("BTC/USDT", long_setup())
        engine.process("BTC/USDT", long_setup())
        self.assertEqual(len(dispatcher.messages), 1)

    def test_stale_candle_is_skipped(self):
        engine, dispatcher = make_engine()
        engine.feed.is_stale = lambda candle, now_ms=None: True
        self.assertIsNone(engine.process("BTC/USDT", long_setup()))
        self.assertEqual(dispatcher.messages, [])


class CooldownTests(unittest.TestCase):
    def test_window_is_per_symbol_and_direction(self):
        cd = Cooldown(minutes=60)
        self.assertTrue(cd.allow("BTC", Direction.LONG, 0))
        self.assertFalse(cd.allow("BTC", Direction.LONG, 30 * 60_000))
        self.assertTrue(cd.allow("BTC", Direction.SHORT, 30 * 60_000))
        self.assertTrue(cd.allow("ETH", Direction.LONG, 30 * 60_000))
        self.assertTrue(cd.allow("BTC", Direction.LONG, 60 * 60_000))


BASE_ENV = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        s = Settings.from_env(BASE_ENV)
        self.assertEqual(s.risk.account_equity, 1_000_000)
        self.assertEqual(s.risk.risk_budget, 5_000)
        self.assertEqual(s.exchange.timeframe, "15m")

    def test_parses_values(self):
        s = Settings.from_env({
            **BASE_ENV,
            "ACCOUNT_EQUITY": "250_000",
            "RISK_PER_TRADE_PCT": "1%",
            "SYMBOLS": "BTC/USDT:USDT, ETH/USDT:USDT",
            "EXCHANGE_ID": "Bybit",
            "MARKET_TYPE": "swap",
        })
        self.assertEqual(s.risk.risk_budget, 2_500)
        self.assertEqual(s.exchange.symbols, ("BTC/USDT:USDT", "ETH/USDT:USDT"))
        self.assertEqual(s.exchange.exchange_id, "bybit")

    def test_reports_every_error_at_once(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({"ACCOUNT_EQUITY": "lots", "STOP_MODE": "magic", "TIMEFRAME": "15x"})
        message = str(ctx.exception)
        for fragment in ["ACCOUNT_EQUITY", "STOP_MODE", "TIMEFRAME", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
            self.assertIn(fragment, message)

    def test_dry_run_needs_no_telegram(self):
        self.assertTrue(Settings.from_env({"DRY_RUN": "true"}).telegram.dry_run)

    def test_risk_percentage_typo_is_rejected(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "RISK_PER_TRADE_PCT": "50"})

    def test_history_must_cover_indicators(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "HISTORY_CANDLES": "100"})  # slow EMA is 200

    def test_secrets_are_not_in_repr(self):
        s = Settings.from_env({**BASE_ENV, "EXCHANGE_API_SECRET": "hunter2"})
        self.assertNotIn("hunter2", repr(s))
        self.assertNotIn("123:abc", repr(s))


if __name__ == "__main__":
    unittest.main()
