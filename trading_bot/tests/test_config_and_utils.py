from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.config import (
    ConfigError,
    DailyLossBasis,
    DrawdownMode,
    NewsSource,
    Secret,
    load_dotenv,
    settings_from_env,
)
from trading_bot.utils import StateCorruptError, StateStore, next_reset, setup_logging, trading_day

NY = ZoneInfo("America/New_York")


class ConfigTests(unittest.TestCase):
    def test_defaults_with_accounts(self) -> None:
        s = settings_from_env({"ACCOUNTS": "a:100000, b:50000"})
        self.assertEqual([a.account_id for a in s.accounts], ["a", "b"])
        self.assertEqual(s.risk.daily_loss_limit_pct, 1.5)
        self.assertIs(s.risk.daily_loss_basis, DailyLossBasis.INITIAL)
        self.assertIs(s.risk.max_drawdown_mode, DrawdownMode.TRAILING_INTRADAY)
        self.assertEqual(s.session.reset_time, time(17, 0))
        self.assertIs(s.news.source, NewsSource.FOREXFACTORY)

    def test_collects_every_error(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            settings_from_env({
                "ACCOUNTS": "bad",
                "DAILY_LOSS_LIMIT_PCT": "abc",
                "MAX_DRAWDOWN_MODE": "sideways",
                "DAILY_RESET_TZ": "Mars/Base",
            })
        message = str(ctx.exception)
        for fragment in ("ACCOUNTS", "DAILY_LOSS_LIMIT_PCT", "MAX_DRAWDOWN_MODE", "DAILY_RESET_TZ"):
            self.assertIn(fragment, message)

    def test_missing_accounts_is_an_error(self) -> None:
        with self.assertRaises(ConfigError):
            settings_from_env({})

    def test_risk_per_trade_cannot_exceed_daily_limit(self) -> None:
        with self.assertRaises(ConfigError):
            settings_from_env({"ACCOUNTS": "a:1000", "RISK_PER_TRADE_PCT": "2", "DAILY_LOSS_LIMIT_PCT": "1"})

    def test_secret_is_not_printed(self) -> None:
        s = settings_from_env({"ACCOUNTS": "a:1000", "CRYPTO_API_KEY": "sk-live-123"})
        self.assertEqual(s.credentials.crypto_api_key.get(), "sk-live-123")
        self.assertNotIn("sk-live-123", repr(s))
        self.assertNotIn("sk-live-123", str(Secret("sk-live-123")))

    def test_dotenv_does_not_override_real_env(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text('TB_TEST_A="from file"\nTB_TEST_B=x # comment\nexport TB_TEST_C=c\n')
            os.environ["TB_TEST_A"] = "real"
            try:
                load_dotenv(env)
                self.assertEqual(os.environ["TB_TEST_A"], "real")
                self.assertEqual(os.environ["TB_TEST_B"], "x")
                self.assertEqual(os.environ["TB_TEST_C"], "c")
            finally:
                for key in ("TB_TEST_A", "TB_TEST_B", "TB_TEST_C"):
                    os.environ.pop(key, None)


class TimeTests(unittest.TestCase):
    def test_trading_day_rolls_at_17_new_york(self) -> None:
        before = datetime(2026, 3, 2, 16, 59, tzinfo=NY)
        after = datetime(2026, 3, 2, 17, 0, tzinfo=NY)
        self.assertEqual(trading_day(before, NY, time(17)), date(2026, 3, 2))
        self.assertEqual(trading_day(after, NY, time(17)), date(2026, 3, 3))

    def test_midnight_reset_is_calendar_day(self) -> None:
        utc = ZoneInfo("UTC")
        ts = datetime(2026, 3, 2, 23, 59, tzinfo=timezone.utc)
        self.assertEqual(trading_day(ts, utc, time(0)), date(2026, 3, 2))

    def test_next_reset_across_dst(self) -> None:
        # US DST starts 2026-03-08: 17:00 NY is 22:00 UTC before, 21:00 UTC after.
        self.assertEqual(
            next_reset(datetime(2026, 3, 6, 23, 0, tzinfo=timezone.utc), NY, time(17)),
            datetime(2026, 3, 7, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            next_reset(datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc), NY, time(17)),
            datetime(2026, 3, 9, 21, 0, tzinfo=timezone.utc),
        )

    def test_naive_datetime_rejected(self) -> None:
        with self.assertRaises(ValueError):
            trading_day(datetime(2026, 3, 2, 12), NY, time(17))


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_round_trip_survives_reopen(self) -> None:
        with StateStore(self.path) as store:
            store.save_account("a", {"trades_today": 3})
            store.append_event("a", "halt:daily_loss", "hit")
        with StateStore(self.path) as store:
            self.assertEqual(store.load_account("a"), {"trades_today": 3})
            self.assertIsNone(store.load_account("missing"))
            self.assertEqual(store.recent_events("a")[0].kind, "halt:daily_loss")

    def test_corrupt_state_raises(self) -> None:
        StateStore(self.path).close()
        conn = sqlite3.connect(self.path)
        conn.execute("INSERT INTO account_state VALUES ('a', '{not json', 'now')")
        conn.commit()
        conn.close()
        with StateStore(self.path) as store, self.assertRaises(StateCorruptError):
            store.load_account("a")


class LoggingTests(unittest.TestCase):
    def test_writes_bot_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = setup_logging(Path(tmp), "INFO", console=False)
            logging.getLogger("trading_bot.test").warning("hello %s", "world")
            for handler in logger.handlers:
                handler.flush()
            text = (Path(tmp) / "bot.log").read_text()
            self.assertRegex(text, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z \| WARNING  \| trading_bot.test \| hello world")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            logger.addHandler(logging.NullHandler())


if __name__ == "__main__":
    unittest.main()
