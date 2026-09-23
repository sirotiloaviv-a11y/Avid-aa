from __future__ import annotations

import dataclasses
import math
import unittest

from crypto_alerts.config import RiskSettings
from crypto_alerts.market_data import Candle
from crypto_alerts.risk_manager import RiskError, RiskManager
from crypto_alerts.strategy import Direction, Signal

RISK = RiskSettings(account_equity=1_000_000, risk_per_trade_pct=0.5, risk_reward_ratio=2.5)


def make_signal(direction=Direction.LONG, entry=100.0, atr=2.0, invalidation=97.0) -> Signal:
    return Signal(
        symbol="BTC/USDT", timeframe="15m", direction=direction, strategy="test",
        candle=Candle(0, entry, entry, entry, entry, 1.0), entry_price=entry, atr=atr, rsi=25.0,
        volume_ratio=3.0, key_level=invalidation, invalidation_level=invalidation,
        reasons=("RSI oversold (25.0 < 30)",), summary="RSI oversold + 3.0x Volume Surge + Support bounce",
    )


class SizingTests(unittest.TestCase):
    def test_loss_at_stop_equals_exact_risk_budget(self):
        rm = RiskManager(RISK)
        units, capped = rm.position_size(entry=64_000.0, stop=63_000.0)
        self.assertFalse(capped)
        self.assertAlmostEqual(units, 5.0)
        self.assertAlmostEqual(units * (64_000 - 63_000), 5_000.0)

    def test_short_side_sizing(self):
        units, _ = RiskManager(RISK).position_size(entry=2_000.0, stop=2_040.0)
        self.assertAlmostEqual(units * 40.0, 5_000.0)

    def test_fees_are_inside_the_budget(self):
        rm = RiskManager(dataclasses.replace(RISK, fee_rate_pct=0.05))
        entry, stop = 100.0, 98.0
        units, _ = rm.position_size(entry, stop)
        loss = units * (entry - stop) + units * entry * 0.0005 + units * stop * 0.0005
        self.assertAlmostEqual(loss, 5_000.0)

    def test_leverage_cap_limits_notional(self):
        rm = RiskManager(dataclasses.replace(RISK, max_leverage=2.0))
        # 0.1% stop -> uncapped notional would be $5M (5x equity).
        units, capped = rm.position_size(entry=100.0, stop=99.9)
        self.assertTrue(capped)
        self.assertAlmostEqual(units * 100.0, 2_000_000.0)

    def test_rounding_down_never_increases_risk(self):
        rm = RiskManager(RISK)
        units, _ = rm.position_size(100.0, 97.0, amount_rounder=lambda u: math.floor(u * 100) / 100)
        self.assertLessEqual(units * 3.0, 5_000.0)
        self.assertAlmostEqual(units, 1666.66)

    def test_size_rounding_to_zero_is_an_error(self):
        with self.assertRaises(RiskError):
            RiskManager(RISK).position_size(100.0, 97.0, amount_rounder=lambda u: 0.0)

    def test_invalid_stop(self):
        with self.assertRaises(RiskError):
            RiskManager(RISK).position_size(100.0, 100.0)


class StopLossTests(unittest.TestCase):
    def test_atr_mode(self):
        rm = RiskManager(dataclasses.replace(RISK, stop_mode="atr", atr_stop_multiplier=1.5))
        stop, method = rm.stop_loss(Direction.LONG, 100.0, 2.0, swing_level=97.0)
        self.assertAlmostEqual(stop, 97.0)
        self.assertIn("ATR", method)
        stop, _ = rm.stop_loss(Direction.SHORT, 100.0, 2.0)
        self.assertAlmostEqual(stop, 103.0)

    def test_swing_mode_adds_buffer_beyond_level(self):
        rm = RiskManager(dataclasses.replace(RISK, stop_mode="swing", swing_buffer_atr=0.2))
        stop, method = rm.stop_loss(Direction.LONG, 100.0, 2.0, swing_level=97.0)
        self.assertAlmostEqual(stop, 96.6)
        self.assertIn("swing low", method)
        stop, _ = rm.stop_loss(Direction.SHORT, 100.0, 2.0, swing_level=103.0)
        self.assertAlmostEqual(stop, 103.4)

    def test_swing_on_wrong_side_falls_back_to_atr(self):
        rm = RiskManager(dataclasses.replace(RISK, stop_mode="swing"))
        stop, _ = rm.stop_loss(Direction.LONG, 100.0, 2.0, swing_level=101.0)
        self.assertAlmostEqual(stop, 97.0)

    def test_hybrid_widens_a_stop_inside_the_noise(self):
        rm = RiskManager(dataclasses.replace(RISK, min_stop_atr=0.5, swing_buffer_atr=0.0))
        stop, method = rm.stop_loss(Direction.LONG, 100.0, 2.0, swing_level=99.8)
        self.assertAlmostEqual(stop, 99.0)
        self.assertIn("widened", method)

    def test_hybrid_replaces_a_far_swing_with_atr(self):
        rm = RiskManager(dataclasses.replace(RISK, max_stop_atr=3.0))
        stop, method = rm.stop_loss(Direction.LONG, 100.0, 2.0, swing_level=90.0)
        self.assertAlmostEqual(stop, 97.0)
        self.assertIn("too far", method)


class PlanTests(unittest.TestCase):
    def test_long_plan(self):
        plan = RiskManager(RISK).build_plan(make_signal())
        # hybrid: 97 - 0.2 * 2 = 96.6, 1.7 ATR away -> within [0.5, 3.0]
        self.assertAlmostEqual(plan.stop_loss, 96.6)
        self.assertAlmostEqual(plan.take_profit, 100 + 2.5 * 3.4)
        self.assertAlmostEqual(plan.risk_amount, 5_000.0)
        self.assertAlmostEqual(plan.reward_amount, 12_500.0)
        self.assertAlmostEqual(plan.stop_loss_pct, -3.4)
        self.assertAlmostEqual(plan.take_profit_pct, 8.5)
        self.assertAlmostEqual(plan.notional, plan.units * 100.0)
        # Zone sits below the reference price for a long.
        self.assertAlmostEqual(plan.entry_zone[0], 100 - 0.15 * 2)
        self.assertEqual(plan.entry_zone[1], 100.0)

    def test_short_plan(self):
        plan = RiskManager(RISK).build_plan(make_signal(Direction.SHORT, invalidation=103.0))
        self.assertAlmostEqual(plan.stop_loss, 103.4)
        self.assertAlmostEqual(plan.take_profit, 100 - 2.5 * 3.4)
        self.assertGreater(plan.stop_loss_pct, 0)
        self.assertLess(plan.take_profit_pct, 0)
        self.assertEqual(plan.entry_zone[0], 100.0)
        self.assertAlmostEqual(plan.risk_amount, 5_000.0)

    def test_any_fill_in_zone_stays_within_budget(self):
        plan = RiskManager(RISK).build_plan(make_signal())
        worst_fill = plan.entry_zone[1]
        self.assertLessEqual(plan.units * (worst_fill - plan.stop_loss), 5_000.0 + 1e-6)

    def test_short_target_below_zero_is_rejected(self):
        rm = RiskManager(dataclasses.replace(RISK, risk_reward_ratio=10, stop_mode="atr", atr_stop_multiplier=5))
        with self.assertRaises(RiskError):
            rm.build_plan(make_signal(Direction.SHORT, entry=10.0, atr=1.0, invalidation=12.0))


if __name__ == "__main__":
    unittest.main()
