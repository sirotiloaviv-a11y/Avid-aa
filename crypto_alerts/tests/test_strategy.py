from __future__ import annotations

import dataclasses
import unittest

from crypto_alerts.indicators import compute_indicators
from crypto_alerts.market_data import Candle
from crypto_alerts.strategy import Direction, RsiVolumeReversalStrategy

from .helpers import INDICATORS, STRATEGY, long_setup, short_setup


def evaluate(candles, settings=STRATEGY):
    frame = compute_indicators(candles, INDICATORS)
    return RsiVolumeReversalStrategy(settings).evaluate("BTC/USDT", "15m", frame)


class LongTriggerTests(unittest.TestCase):
    def test_fires_with_all_conditions(self):
        signal = evaluate(long_setup())
        self.assertIsNotNone(signal)
        self.assertIs(signal.direction, Direction.LONG)
        self.assertLess(signal.rsi, 30)
        self.assertGreaterEqual(signal.volume_ratio, 2.5)
        self.assertEqual(signal.key_level, 99.8)
        # Invalidation is the lower of the wick (99.95) and the support (99.8).
        self.assertEqual(signal.invalidation_level, 99.8)
        self.assertEqual(signal.entry_price, 100.0)
        self.assertIn("Support bounce", signal.summary)
        self.assertEqual(len(signal.reasons), 3)

    def test_no_signal_without_volume_spike(self):
        self.assertIsNone(evaluate(long_setup(signal_volume=150.0)))

    def test_no_signal_without_support_nearby(self):
        candles = long_setup()
        last = candles[-1]
        # Same candle, but 5 ATR above any swing low.
        shifted = dataclasses.replace(last, open=last.open + 5, high=last.high + 5,
                                      low=last.low + 5, close=last.close + 5)
        self.assertIsNone(evaluate(candles[:-1] + [shifted]))

    def test_no_signal_on_bearish_candle(self):
        candles = long_setup()
        last = candles[-1]
        # Red candle closing at its low: no bullish reaction.
        red = Candle(last.timestamp, last.open, last.open + 0.05, 99.95, 99.96, last.volume)
        self.assertIsNone(evaluate(candles[:-1] + [red]))

    def test_trend_filter_blocks_counter_trend_long(self):
        settings = dataclasses.replace(STRATEGY, trend_filter=True)
        self.assertIsNone(evaluate(long_setup(), settings))

    def test_not_enough_history(self):
        self.assertIsNone(evaluate(long_setup()[:10]))


class ConvictionTests(unittest.TestCase):
    def test_fixture_has_no_extreme_factors(self):
        # RSI 24.4 is oversold but not extreme (<= 20); 4x volume is below 2 x 2.5 = 5x.
        self.assertEqual(evaluate(long_setup()).conviction_factors, ())

    def test_extreme_volume(self):
        signal = evaluate(long_setup(signal_volume=600.0))
        self.assertEqual(signal.conviction_factors, ("Extreme volume (6.0x)",))

    def test_extreme_rsi_and_trend_thresholds_are_configurable(self):
        settings = dataclasses.replace(STRATEGY, extreme_rsi_margin=5.0)
        factors = evaluate(long_setup(), settings).conviction_factors
        self.assertEqual(len(factors), 1)
        self.assertTrue(factors[0].startswith("Extreme RSI"))

    def test_counter_trend_long_gets_no_trend_factor(self):
        factors = evaluate(long_setup(signal_volume=600.0)).conviction_factors
        self.assertFalse(any("trend" in f for f in factors))  # fixture closes below the slow EMA


class ShortTriggerTests(unittest.TestCase):
    def test_fires_on_mirrored_setup(self):
        signal = evaluate(short_setup())
        self.assertIsNotNone(signal)
        self.assertIs(signal.direction, Direction.SHORT)
        self.assertGreater(signal.rsi, 70)
        self.assertAlmostEqual(signal.key_level, 210 - 99.8)
        self.assertAlmostEqual(signal.invalidation_level, 210 - 99.8)
        self.assertIn("Resistance rejection", signal.summary)


if __name__ == "__main__":
    unittest.main()
