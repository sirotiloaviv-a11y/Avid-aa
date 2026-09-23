"""Order-book slippage maths and the liquidity guard actions."""

from __future__ import annotations

import unittest

from crypto_alerts.config import LiquiditySettings, RiskSettings
from crypto_alerts.market_data import OrderBook
from crypto_alerts.risk_manager import (
    RiskError,
    RiskManager,
    check_liquidity,
    max_units_within,
    simulate_fill,
)
from crypto_alerts.strategy import Direction

from .helpers import make_book
from .test_risk_manager import make_signal

# mid = 100; asks 100.1 x1, 100.2 x1, 101 x10 ; bids 99.9 x1, 99.8 x1, 99 x10
BOOK = OrderBook(
    "BTC/USDT",
    bids=((99.9, 1.0), (99.8, 1.0), (99.0, 10.0)),
    asks=((100.1, 1.0), (100.2, 1.0), (101.0, 10.0)),
)


class FillSimulationTests(unittest.TestCase):
    def test_walks_levels(self):
        filled, avg = simulate_fill(BOOK.asks, 3.0)
        self.assertEqual(filled, 3.0)
        self.assertAlmostEqual(avg, (100.1 + 100.2 + 101.0) / 3)

    def test_partial_when_depth_runs_out(self):
        filled, avg = simulate_fill(BOOK.asks, 50.0)
        self.assertEqual(filled, 12.0)

    def test_empty_side(self):
        self.assertEqual(simulate_fill((), 1.0), (0.0, None))


class MaxUnitsTests(unittest.TestCase):
    def test_buy_side_solves_partial_level(self):
        # Limit 100.3: take 100.1 and 100.2 whole (cost 200.3, 2 units), then
        # q at 101 so that (200.3 + 101 q) / (2 + q) = 100.3 -> q = 0.3 / 0.7.
        units = max_units_within(BOOK.asks, 100.3, buying=True)
        self.assertAlmostEqual(units, 2 + 0.3 / 0.7)
        _, avg = simulate_fill(BOOK.asks, units)
        self.assertAlmostEqual(avg, 100.3)

    def test_sell_side_mirrors(self):
        units = max_units_within(BOOK.bids, 99.7, buying=False)
        self.assertAlmostEqual(units, 2 + 0.3 / 0.7)
        _, avg = simulate_fill(BOOK.bids, units)
        self.assertAlmostEqual(avg, 99.7)

    def test_limit_inside_spread_allows_nothing(self):
        self.assertEqual(max_units_within(BOOK.asks, 100.05, buying=True), 0.0)

    def test_whole_book_within_limit_returns_depth(self):
        self.assertEqual(max_units_within(BOOK.asks, 200.0, buying=True), 12.0)


class CheckLiquidityTests(unittest.TestCase):
    def test_slippage_is_measured_against_mid(self):
        check = check_liquidity(BOOK, Direction.LONG, 1.0, max_slippage_pct=0.2)
        self.assertAlmostEqual(check.mid_price, 100.0)
        self.assertAlmostEqual(check.slippage_pct, 0.1)  # half the spread
        self.assertAlmostEqual(check.spread_pct, 0.2)
        self.assertTrue(check.ok)

    def test_short_uses_bids(self):
        check = check_liquidity(BOOK, Direction.SHORT, 2.0, max_slippage_pct=0.1)
        self.assertEqual(check.side, "sell")
        self.assertAlmostEqual(check.avg_fill_price, 99.85)
        self.assertAlmostEqual(check.slippage_pct, 0.15)
        self.assertFalse(check.ok)

    def test_unfillable_size_is_not_ok(self):
        check = check_liquidity(BOOK, Direction.LONG, 100.0, max_slippage_pct=5)
        self.assertFalse(check.fully_filled)
        self.assertFalse(check.ok)

    def test_one_sided_book_is_an_error(self):
        with self.assertRaises(RiskError):
            check_liquidity(OrderBook("X", (), BOOK.asks), Direction.LONG, 1.0, 0.1)


class GuardActionTests(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskSettings())
        self.plan = self.rm.build_plan(make_signal())  # ~1470 units at 100
        self.thin = make_book(100.0, depth_units=1000)   # cannot fill it
        self.deep = make_book(100.0, depth_units=1e6)

    def test_deep_book_passes(self):
        plan = self.rm.apply_liquidity(self.plan, self.deep, LiquiditySettings())
        self.assertEqual(plan.liquidity_action, "ok")
        self.assertEqual(plan.units, self.plan.units)
        # Slippage makes the realised loss at the stop slightly larger than budget.
        self.assertGreater(plan.risk_with_slippage, plan.risk_amount)

    def test_warn_keeps_size(self):
        plan = self.rm.apply_liquidity(self.plan, self.thin, LiquiditySettings(action="warn"))
        self.assertEqual(plan.liquidity_action, "warned")
        self.assertEqual(plan.units, self.plan.units)

    def test_filter(self):
        plan = self.rm.apply_liquidity(self.plan, self.thin, LiquiditySettings(action="filter"))
        self.assertEqual(plan.liquidity_action, "filtered")

    def test_reduce_shrinks_to_threshold_and_lowers_risk(self):
        settings = LiquiditySettings(action="reduce", max_slippage_pct=0.1)
        plan = self.rm.apply_liquidity(self.plan, self.thin, settings, amount_rounder=lambda u: int(u))
        self.assertEqual(plan.liquidity_action, "reduced")
        self.assertEqual(plan.original_units, self.plan.units)
        self.assertLess(plan.units, self.plan.units)
        self.assertEqual(plan.units, int(plan.units))  # rounded down via the exchange rounder
        self.assertTrue(plan.liquidity.ok)
        self.assertLessEqual(plan.liquidity.slippage_pct, 0.1)
        self.assertLess(plan.risk_amount, self.plan.risk_amount)
        self.assertAlmostEqual(plan.notional, plan.units * plan.entry)

    def test_reduce_to_nothing_filters(self):
        wide = make_book(100.0, depth_units=1000, spread_pct=1.0)  # half-spread alone is 0.5%
        plan = self.rm.apply_liquidity(self.plan, wide, LiquiditySettings(action="reduce"))
        self.assertEqual(plan.liquidity_action, "filtered")


class LiveAccountUpdateTests(unittest.TestCase):
    def test_update_changes_next_plan(self):
        rm = RiskManager(RiskSettings())
        rm.update_account(account_equity=200_000, risk_per_trade_pct=1.0)
        self.assertEqual(rm.risk_budget, 2_000)
        self.assertAlmostEqual(rm.build_plan(make_signal()).risk_amount, 2_000)

    def test_partial_update_keeps_other_value(self):
        rm = RiskManager(RiskSettings())
        rm.update_account(risk_per_trade_pct=0.25)
        self.assertEqual(rm.settings.account_equity, 1_000_000)

    def test_rejects_bad_values(self):
        rm = RiskManager(RiskSettings())
        for equity, pct in [(0, None), (-5, None), (float("nan"), None), (None, 0), (None, 6)]:
            with self.assertRaises(RiskError):
                rm.update_account(equity, pct)
        self.assertEqual(rm.risk_budget, 5_000)


if __name__ == "__main__":
    unittest.main()
