"""Headless checks for the parts of app.py that are not UI.

Streamlit and pandas are stubbed, so this runs with nothing installed:

    python trading_dashboard/test_engine.py
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path


def _install_stubs() -> None:
    """Stand in for streamlit/pandas so app.py imports without the UI stack."""
    if "streamlit" not in sys.modules:
        streamlit = types.ModuleType("streamlit")

        def cache_resource(*args, **kwargs):
            if args and callable(args[0]):
                return args[0]
            return lambda fn: fn

        streamlit.cache_resource = cache_resource
        components_v1 = types.ModuleType("streamlit.components.v1")
        components_v1.html = lambda *a, **k: None
        components = types.ModuleType("streamlit.components")
        components.v1 = components_v1
        streamlit.components = components
        sys.modules["streamlit"] = streamlit
        sys.modules["streamlit.components"] = components
        sys.modules["streamlit.components.v1"] = components_v1

    if "pandas" not in sys.modules:
        pandas = types.ModuleType("pandas")
        pandas.DataFrame = lambda rows=(), *a, **k: rows
        sys.modules["pandas"] = pandas


_install_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app  # noqa: E402


class PositionMathTest(unittest.TestCase):
    def test_average_price_on_adds(self) -> None:
        position = app.Position("BTCUSDT")
        position.apply_fill(app.Side.BUY, 1.0, 100.0)
        position.apply_fill(app.Side.BUY, 1.0, 110.0)
        self.assertAlmostEqual(position.qty, 2.0)
        self.assertAlmostEqual(position.avg_price, 105.0)

    def test_realized_pnl_on_close(self) -> None:
        position = app.Position("BTCUSDT")
        position.apply_fill(app.Side.BUY, 2.0, 100.0)
        realized = position.apply_fill(app.Side.SELL, 2.0, 105.0)
        self.assertAlmostEqual(realized, 10.0)
        self.assertEqual(position.qty, 0.0)
        self.assertEqual(position.avg_price, 0.0)

    def test_reversal_rebases_average(self) -> None:
        position = app.Position("BTCUSDT")
        position.apply_fill(app.Side.BUY, 1.0, 100.0)
        realized = position.apply_fill(app.Side.SELL, 3.0, 120.0)
        self.assertAlmostEqual(realized, 20.0)
        self.assertAlmostEqual(position.qty, -2.0)
        self.assertAlmostEqual(position.avg_price, 120.0)

    def test_short_unrealized_is_inverted(self) -> None:
        position = app.Position("BTCUSDT")
        position.apply_fill(app.Side.SELL, 2.0, 100.0)
        self.assertAlmostEqual(position.unrealized(90.0), 20.0)
        self.assertAlmostEqual(position.unrealized(110.0), -20.0)


class FeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = app.MarketDataFeed(app.SYMBOLS, app.EventLog())

    def test_history_is_seeded(self) -> None:
        for symbol in app.SYMBOLS:
            self.assertGreater(self.feed.last_price(symbol), 0.0)

    def test_candles_are_ordered_and_unique(self) -> None:
        candles = self.feed.candles("BTCUSDT", 5)
        self.assertGreater(len(candles), 10)
        times = [c.time for c in candles]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))
        for candle in candles:
            self.assertLessEqual(candle.low, candle.open)
            self.assertLessEqual(candle.low, candle.close)
            self.assertGreaterEqual(candle.high, candle.open)
            self.assertGreaterEqual(candle.high, candle.close)

    def test_bar_size_changes_bar_count(self) -> None:
        fast = self.feed.candles("ETHUSDT", 1, limit=10_000)
        slow = self.feed.candles("ETHUSDT", 60, limit=10_000)
        self.assertGreater(len(fast), len(slow))


class RoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = app.TradingEngine()      # not started: no background thread
        self.router = self.engine.router
        self.portfolio = self.engine.portfolio
        self.router.REJECT_RATE = 0.0          # determinism for the happy path

    def test_market_order_fills_master_and_copies(self) -> None:
        request = app.OrderRequest("BTCUSDT", app.Side.BUY, 1.0, app.OrderType.MARKET)
        reports = self.router.submit(request)
        self.assertEqual(len(reports), 1 + len(self.portfolio.subs()))
        self.assertTrue(all(r.status is app.ExecStatus.FILLED for r in reports))
        self.assertAlmostEqual(self.portfolio.master.position("BTCUSDT").qty, 1.0)
        sub = self.portfolio.accounts["SUB-A1"]
        self.assertAlmostEqual(sub.position("BTCUSDT").qty, 0.25)

    def test_copy_targets_are_respected(self) -> None:
        request = app.OrderRequest("ETHUSDT", app.Side.SELL, 2.0, app.OrderType.MARKET,
                                   targets=["prop.desk@fundedfx.io"])
        reports = self.router.submit(request)
        touched = {r.account_id for r in reports}
        self.assertEqual(touched, {"MASTER-001", "SUB-B1", "SUB-B2", "SUB-B3"})

    def test_limit_orders_rest_then_fill_on_touch(self) -> None:
        mark = self.engine.feed.last_price("BTCUSDT")
        request = app.OrderRequest("BTCUSDT", app.Side.BUY, 1.0, app.OrderType.LIMIT,
                                   limit_price=mark - 500.0)
        reports = self.router.submit(request)
        self.assertTrue(all(r.status is app.ExecStatus.WORKING for r in reports))
        self.assertEqual(self.portfolio.master.position("BTCUSDT").qty, 0.0)

        self.portfolio.on_tick({"BTCUSDT": mark - 600.0})
        self.assertAlmostEqual(self.portfolio.master.position("BTCUSDT").qty, 1.0)
        self.assertEqual(self.portfolio.working_for("BTCUSDT"), [])

    def test_invalid_quantity_is_rejected_without_copies(self) -> None:
        request = app.OrderRequest("BTCUSDT", app.Side.BUY, 0.0, app.OrderType.MARKET)
        reports = self.router.submit(request)
        self.assertEqual(len(reports), 1)
        self.assertIs(reports[0].status, app.ExecStatus.REJECTED)

    def test_broker_failures_do_not_raise(self) -> None:
        self.router.REJECT_RATE = 1.0
        reports = self.router.submit(
            app.OrderRequest("BTCUSDT", app.Side.BUY, 1.0, app.OrderType.MARKET)
        )
        self.assertEqual(len(reports), 1)                       # master failed, no fan-out
        self.assertIs(reports[0].status, app.ExecStatus.REJECTED)

    def test_disconnected_and_killed_accounts_are_skipped(self) -> None:
        self.portfolio.accounts["SUB-A1"].status = app.AccountStatus.DISCONNECTED
        self.portfolio.kill("SUB-A2", self.engine.marks(), "test")
        reports = self.router.submit(
            app.OrderRequest("BTCUSDT", app.Side.BUY, 1.0, app.OrderType.MARKET)
        )
        skipped = {r.account_id for r in reports if r.status is app.ExecStatus.SKIPPED}
        self.assertEqual(skipped, {"SUB-A1", "SUB-A2"})


class RiskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = app.TradingEngine()
        self.engine.router.REJECT_RATE = 0.0
        self.portfolio = self.engine.portfolio

    def test_kill_switch_trips_and_flattens(self) -> None:
        account = self.portfolio.accounts["SUB-B1"]
        entry = self.engine.feed.last_price("BTCUSDT")
        account.position("BTCUSDT").apply_fill(app.Side.BUY, 1.0, entry)

        # A drop large enough to blow through a 5% drawdown budget on 100k.
        self.portfolio.on_tick({"BTCUSDT": entry - 8_000.0})
        self.assertIs(account.status, app.AccountStatus.KILLED)
        self.assertEqual(account.open_positions(), [])
        self.assertLess(account.realized_pnl(), 0.0)

    def test_reinstate_rebaselines_the_peak(self) -> None:
        account = self.portfolio.accounts["SUB-B1"]
        self.portfolio.kill(account.account_id, self.engine.marks(), "manual")
        self.portfolio.reinstate(account.account_id)
        self.assertIs(account.status, app.AccountStatus.ACTIVE)
        self.assertAlmostEqual(account.drawdown_pct(self.engine.marks()), 0.0, places=6)

    def test_halt_all_blocks_new_orders(self) -> None:
        self.portfolio.kill_all(self.engine.marks(), "manual halt")
        reports = self.engine.router.submit(
            app.OrderRequest("BTCUSDT", app.Side.BUY, 1.0, app.OrderType.MARKET)
        )
        self.assertIs(reports[0].status, app.ExecStatus.REJECTED)

    def test_session_status_rolls_up_worst_member(self) -> None:
        members = self.portfolio.by_email()["prop.desk@fundedfx.io"]
        members[0].status = app.AccountStatus.DISCONNECTED
        self.assertIs(app.Portfolio.session_status(members),
                      app.AccountStatus.DISCONNECTED)


class ChartPayloadTest(unittest.TestCase):
    def test_payload_is_json_serializable(self) -> None:
        engine = app.TradingEngine()
        candles = engine.feed.candles("BTCUSDT", 5)
        payload = {
            "candles": [
                dict(time=c.time, open=c.open, high=c.high, low=c.low, close=c.close)
                for c in candles
            ]
        }
        encoded = json.dumps(payload)
        html = app._CHART_HTML.replace("__PAYLOAD__", encoded)
        self.assertNotIn("__PAYLOAD__", html)
        self.assertIn("addCandlestickSeries", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
