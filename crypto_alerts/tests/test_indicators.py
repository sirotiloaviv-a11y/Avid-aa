from __future__ import annotations

import unittest

from crypto_alerts.indicators import atr, ema, rsi, sma, swing_highs, swing_lows, volume_ratio


class MovingAverageTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_sma_too_short(self):
        self.assertEqual(sma([1, 2], 3), [None, None])

    def test_ema_seeds_with_sma_then_smooths(self):
        out = ema([1, 2, 3, 4], 3)
        self.assertEqual(out[:3], [None, None, 2.0])
        self.assertAlmostEqual(out[3], 0.5 * 4 + 0.5 * 2.0)


class RsiTests(unittest.TestCase):
    def test_only_gains_is_100(self):
        self.assertEqual(rsi(list(range(1, 20)), 14)[-1], 100.0)

    def test_only_losses_is_0(self):
        self.assertEqual(rsi(list(range(20, 1, -1)), 14)[-1], 0.0)

    def test_flat_is_50(self):
        self.assertEqual(rsi([5.0] * 20, 14)[-1], 50.0)

    def test_warmup_is_none(self):
        out = rsi(list(range(30)), 14)
        self.assertTrue(all(v is None for v in out[:14]))
        self.assertIsNotNone(out[14])

    def test_wilder_reference_value(self):
        # Wilder's original worked example (New Concepts in Technical Trading Systems).
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                  45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
        out = rsi(closes, 14)
        self.assertAlmostEqual(out[14], 70.46, delta=0.05)
        self.assertAlmostEqual(out[15], 66.25, delta=0.05)


class AtrTests(unittest.TestCase):
    def test_constant_range(self):
        highs, lows, closes = [11.0] * 20, [9.0] * 20, [10.0] * 20
        self.assertAlmostEqual(atr(highs, lows, closes, 14)[-1], 2.0)

    def test_gap_counts_toward_true_range(self):
        highs, lows, closes = [11.0, 21.0], [9.0, 19.0], [10.0, 20.0]
        # Second candle's TR is |21 - 10| = 11, not 21 - 19.
        self.assertAlmostEqual(atr(highs, lows, closes, 2)[-1], (2 + 11) / 2)


class VolumeRatioTests(unittest.TestCase):
    def test_baseline_excludes_current_candle(self):
        out = volume_ratio([100.0] * 20 + [300.0], 20)
        self.assertEqual(out[-1], 3.0)
        self.assertIsNone(out[19])

    def test_zero_baseline_is_none(self):
        self.assertIsNone(volume_ratio([0.0] * 5 + [10.0], 5)[-1])


class SwingTests(unittest.TestCase):
    def test_swing_low_needs_confirmation_on_both_sides(self):
        lows = [5, 4, 3, 2, 3, 4, 5, 1]
        self.assertEqual(swing_lows(lows, 3), [3])
        # The final candle is the lowest but unconfirmed — no look-ahead.
        self.assertNotIn(7, swing_lows(lows, 3))

    def test_swing_high(self):
        self.assertEqual(swing_highs([1, 2, 3, 9, 3, 2, 1], 3), [3])

    def test_flat_top_counts_once(self):
        self.assertEqual(swing_highs([1, 2, 3, 9, 9, 2, 1, 0], 2), [3])


if __name__ == "__main__":
    unittest.main()
