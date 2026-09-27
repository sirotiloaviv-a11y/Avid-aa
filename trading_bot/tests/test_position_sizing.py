from __future__ import annotations

import unittest
from decimal import Decimal

from trading_bot.risk_manager import (
    PositionSizingError,
    calculate_position_size,
    get_instrument,
)


class PositionSizingTests(unittest.TestCase):
    def test_nq_contracts(self) -> None:
        nq = get_instrument("NQ")
        # 20-point stop = 80 ticks * $5 = $400 + $4 fees = $404 per contract.
        size = calculate_position_size(nq, 20000, 19980, 1500)
        self.assertEqual(size.stop_ticks, 80)
        self.assertEqual(size.risk_per_unit, Decimal("404.00"))
        self.assertEqual(size.quantity, Decimal("3"))
        self.assertLessEqual(size.total_risk, Decimal("1500"))

    def test_short_trade_uses_absolute_distance(self) -> None:
        mnq = get_instrument("mnq")
        size = calculate_position_size(mnq, 20000, 20010, 500)
        # 40 ticks * $0.50 + $1 = $21 per contract -> 23 contracts.
        self.assertEqual(size.quantity, Decimal("23"))

    def test_partial_tick_stop_rounds_up(self) -> None:
        nq = get_instrument("NQ")
        size = calculate_position_size(nq, 20000, 19999.9, 1000)
        self.assertEqual(size.stop_ticks, 1)

    def test_crypto_quantity_rounds_down_to_step(self) -> None:
        btc = get_instrument("BTCUSDT")
        # $500 budget, $1,234.5 stop -> 0.40502... BTC -> 0.405.
        size = calculate_position_size(btc, 60000, 58765.5, 500)
        self.assertEqual(size.quantity, Decimal("0.405"))
        self.assertLessEqual(size.total_risk, Decimal("500"))

    def test_below_minimum_is_rejected_not_rounded_up(self) -> None:
        nq = get_instrument("NQ")
        size = calculate_position_size(nq, 20000, 19900, 1000)  # $2,004 per contract
        self.assertFalse(size.is_tradeable)
        self.assertEqual(size.quantity, 0)
        self.assertIn("minimum size", size.rejected_reason or "")

    def test_capped_at_max_quantity(self) -> None:
        nq = get_instrument("NQ")
        size = calculate_position_size(nq, 20000, 19999.75, 1_000_000)
        self.assertEqual(size.quantity, nq.max_qty)

    def test_zero_budget(self) -> None:
        size = calculate_position_size(get_instrument("NQ"), 20000, 19990, 0)
        self.assertFalse(size.is_tradeable)

    def test_invalid_inputs(self) -> None:
        nq = get_instrument("NQ")
        with self.assertRaises(PositionSizingError):
            calculate_position_size(nq, 20000, 20000, 1000)
        with self.assertRaises(PositionSizingError):
            calculate_position_size(nq, float("nan"), 19990, 1000)
        with self.assertRaises(PositionSizingError):
            get_instrument("DOGE")


if __name__ == "__main__":
    unittest.main()
