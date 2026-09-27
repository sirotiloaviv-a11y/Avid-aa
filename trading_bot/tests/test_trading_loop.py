from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path

from trading_bot.brokers import ReplayFeed
from trading_bot.config import BrokerKind, ConfigError, MarketDataSource, settings_from_env
from trading_bot.main import build_brokers, build_feed
from trading_bot.risk_manager import RiskEvent, TradeClosedEvent, TradeOpenedEvent
from trading_bot.runtime import BotRuntime
from trading_bot.utils import StateStore

from .test_strategies import candles, v_shape

M5 = timedelta(minutes=5)


def write_csv(path: Path) -> None:
    # NQ: down then up (LONG cross), then a flush through the stop.
    nq = candles("NQ", v_shape(15, 10) + [19800.0, 19700.0])
    btc = candles("BTCUSDT", [60000 + 5 * i for i in range(27)])
    lines = ["symbol,start,open,high,low,close,volume"]
    for c in nq + btc:
        lines.append(f"{c.symbol},{c.start.isoformat()},{c.open},{c.high},{c.low},{c.close},1")
    path.write_text("\n".join(lines) + "\n")


class TradingLoopEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_csv(self.dir / "bars.csv")
        self.env = {
            "ACCOUNTS": "apex_1:50000,apex_2:100000,crypto_1:100000",
            "ACCOUNT_ROUTES": "apex_1=paper:futures,apex_2=paper:futures,crypto_1=paper:crypto",
            "TRADING_ENABLED": "true",
            "MARKET_DATA": "replay",
            "MARKET_DATA_REPLAY_FILE": str(self.dir / "bars.csv"),
            "EMA_FAST": "3", "EMA_SLOW": "6", "ATR_PERIOD": "3",
            "RISK_PER_TRADE_PCT": "1.0", "DAILY_LOSS_LIMIT_PCT": "3", "MAX_DRAWDOWN_PCT": "6",
            "NEWS_CALENDAR_SOURCE": "none",
            "ACCOUNT_POLL_SECONDS": "0.01",
            "STATE_DB_PATH": str(self.dir / "state" / "bot.db"),
            "LOG_DIR": str(self.dir / "logs"),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_signal_to_multi_account_execution_to_journal(self) -> None:
        settings = settings_from_env(self.env)
        runtime = BotRuntime(settings, enable_telegram=False, enable_dashboard=False)
        events: list[RiskEvent] = []
        runtime.manager.subscribe(events.append)
        assert runtime.trading is not None
        feed = runtime.trading.feed
        assert isinstance(feed, ReplayFeed)
        runtime.start()
        try:
            deadline = time.monotonic() + 10
            while not feed.done.is_set() and time.monotonic() < deadline:
                runtime.trading.step(timeout=0.05)
            for _ in range(5):
                runtime.trading.step(timeout=0.05)
        finally:
            runtime.stop()

        opened = [e for e in events if isinstance(e, TradeOpenedEvent)]
        closed = [e for e in events if isinstance(e, TradeClosedEvent)]
        # LONG on the V's upswing (futures accounts only; BTC never crosses),
        # target hit on the way up. The SHORT on the final flush is refused
        # by the risk engine: its ATR stop is wider than the risk budget.
        self.assertEqual(sorted((e.account_id, e.direction and e.direction.value) for e in opened),
                         [("apex_1", "long"), ("apex_2", "long")])
        self.assertEqual({e.symbol for e in opened}, {"NQ"})
        self.assertEqual(sorted(e.account_id for e in closed), ["apex_1", "apex_2"])
        self.assertEqual({e.reason.value for e in closed}, {"tp"})
        self.assertTrue(all(e.realized_pnl > 0 for e in closed))
        with StateStore(settings.state_db_path) as store:
            trades = store.recent_trades(10)
            self.assertEqual(sorted(t.exit_reason or "open" for t in trades), ["tp", "tp"])
            saved = store.load_account("apex_1")
            assert saved is not None
            self.assertGreater(saved["balance"], 50_000)  # paper profit reached the risk state

    def test_graceful_shutdown_via_stop_event(self) -> None:
        settings = settings_from_env({**self.env, "MARKET_DATA": "simulated", "SIMULATED_BAR_SECONDS": "0.05"})
        runtime = BotRuntime(settings, enable_telegram=False, enable_dashboard=False)
        stop = threading.Event()
        runtime.start()
        worker = threading.Thread(target=runtime.run_until, args=(stop,))
        worker.start()
        time.sleep(0.5)
        stop.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        assert runtime.trading is not None
        self.assertGreater(runtime.trading.candles_seen, 0)
        runtime.stop()

    def test_trading_disabled_by_default(self) -> None:
        env = {k: v for k, v in self.env.items() if k != "TRADING_ENABLED"}
        runtime = BotRuntime(settings_from_env(env), enable_telegram=False, enable_dashboard=False)
        try:
            self.assertIsNone(runtime.trading)
        finally:
            runtime.stop()


class TradingConfigTests(unittest.TestCase):
    base = {"ACCOUNTS": "apex_1:50000,crypto_1:100000"}

    def test_routes_and_defaults(self) -> None:
        s = settings_from_env({**self.base, "ACCOUNT_ROUTES": "apex_1=tradovate:APEX-123",
                               "TRADOVATE_USERNAME": "u", "TRADOVATE_PASSWORD": "p",
                               "TRADOVATE_CID": "1", "TRADOVATE_SECRET": "s",
                               "TRADOVATE_CONTRACTS": "NQ:NQZ6"})
        self.assertFalse(s.trading.enabled)
        apex, crypto = s.trading.routes
        self.assertEqual((apex.broker, apex.broker_account), (BrokerKind.TRADOVATE, "APEX-123"))
        self.assertEqual(crypto.broker, BrokerKind.PAPER)
        self.assertNotIn("'p'", repr(s))

    def test_bybit_keys_per_account(self) -> None:
        s = settings_from_env({**self.base, "ACCOUNT_ROUTES": "crypto_1=bybit",
                               "BYBIT_API_KEY_CRYPTO_1": "k", "BYBIT_API_SECRET_CRYPTO_1": "sec"})
        (account, key, secret), = s.trading.bybit_keys
        self.assertEqual((account, key.get(), secret.get()), ("crypto_1", "k", "sec"))

    def test_invalid_combinations(self) -> None:
        bad = [
            {"ACCOUNT_ROUTES": "ghost=paper"},
            {"ACCOUNT_ROUTES": "apex_1=ibkr"},
            {"ACCOUNT_ROUTES": "apex_1=tradovate"},                       # no account name
            {"ACCOUNT_ROUTES": "apex_1=tradovate:X"},                     # no credentials
            {"ACCOUNT_ROUTES": "crypto_1=bybit"},                         # no key
            {"STRATEGY_SYMBOLS": "NQ,DOGE"},
            {"EMA_FAST": "30", "EMA_SLOW": "10"},
            {"MARKET_DATA": "replay"},
            {"ENVIRONMENT": "live", "TRADING_ENABLED": "true", "MARKET_DATA": "simulated"},
        ]
        for extra in bad:
            with self.assertRaises(ConfigError, msg=str(extra)):
                settings_from_env({**self.base, **extra})

    def test_paper_builders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, StateStore(Path(tmp) / "s.db") as store:
            s = settings_from_env({**self.base, "ACCOUNT_ROUTES": "apex_1=paper:futures",
                                   "MARKET_DATA": "simulated"})
            brokers, routes = build_brokers(s, store)
            self.assertEqual(list(brokers), ["paper"])
            self.assertEqual({r.account_id: len(r.asset_classes) for r in routes}, {"apex_1": 1, "crypto_1": 2})
            self.assertEqual(s.trading.market_data, MarketDataSource.SIMULATED)
            feed = build_feed(s, brokers)
            self.assertEqual(type(feed).__name__, "SimulatedFeed")


if __name__ == "__main__":
    unittest.main()
