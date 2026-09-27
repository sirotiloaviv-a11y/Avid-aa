from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Sequence

from trading_bot.strategies import (
    ATR,
    EMA,
    BarCloseDetector,
    Candle,
    CandleBuilder,
    EmaCrossStrategy,
    Side,
    Signal,
    Tick,
    bar_start,
)

T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
M5 = timedelta(minutes=5)


def candles(symbol: str, closes: Sequence[float], *, start: datetime = T0, spread: float = 2.0) -> list[Candle]:
    bars: list[Candle] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        high = max(prev, close) + spread
        low = min(prev, close) - spread
        bars.append(Candle(symbol, start + i * M5, M5, prev, high, low, close))
        prev = close
    return bars


def v_shape(n_down: int = 30, n_up: int = 30, top: float = 20000.0, step: float = 10.0) -> list[float]:
    down = [top - step * i for i in range(n_down)]
    bottom = down[-1]
    return down + [bottom + step * (i + 1) for i in range(n_up)]


class IndicatorTests(unittest.TestCase):
    def test_ema_seeds_with_sma_then_smooths(self) -> None:
        ema = EMA(3)
        self.assertIsNone(ema.update(1))
        self.assertIsNone(ema.update(2))
        self.assertEqual(ema.update(3), 2.0)       # SMA seed
        self.assertEqual(ema.update(6), 4.0)       # 2 + 0.5 * (6 - 2)
        self.assertTrue(ema.ready)

    def test_atr_wilder(self) -> None:
        atr = ATR(2)
        self.assertIsNone(atr.update(10, 8, 9))    # TR 2
        self.assertEqual(atr.update(12, 9, 11), 2.5)  # TR max(3, 3, 0) = 3 -> mean(2, 3)
        self.assertEqual(atr.update(11, 10, 10.5), 1.75)  # TR 1 -> (2.5 + 1) / 2

    def test_invalid_periods(self) -> None:
        with self.assertRaises(ValueError):
            EMA(0)
        with self.assertRaises(ValueError):
            ATR(0)


class SignalTests(unittest.TestCase):
    def test_validation(self) -> None:
        Signal("s", "NQ", Side.LONG, T0, 100.0, stop=99.0, take_profit=102.0)
        Signal("s", "NQ", Side.FLAT, T0, 100.0)
        with self.assertRaises(ValueError):
            Signal("s", "NQ", Side.LONG, T0, 100.0)  # no stop
        with self.assertRaises(ValueError):
            Signal("s", "NQ", Side.LONG, T0, 100.0, stop=101.0)
        with self.assertRaises(ValueError):
            Signal("s", "NQ", Side.SHORT, T0, 100.0, stop=101.0, take_profit=102.0)

    def test_candle_validation(self) -> None:
        with self.assertRaises(ValueError):
            Candle("NQ", T0, M5, 10, 9, 8, 10)  # high below open


class CandleHelperTests(unittest.TestCase):
    def test_bar_start(self) -> None:
        self.assertEqual(bar_start(T0 + timedelta(minutes=7, seconds=3), M5), T0 + timedelta(minutes=5))

    def test_builder_emits_bar_when_next_starts(self) -> None:
        builder = CandleBuilder(M5)
        for minute, price in ((0, 10.0), (1, 12.0), (3, 9.0), (4, 11.0)):
            self.assertIsNone(builder.add(Tick("NQ", T0 + timedelta(minutes=minute), price, 1)))
        bar = builder.add(Tick("NQ", T0 + timedelta(minutes=5), 11.5, 1))
        self.assertEqual(bar, Candle("NQ", T0, M5, 10.0, 12.0, 9.0, 11.0, 4.0))
        self.assertIsNone(builder.add(Tick("NQ", T0 + timedelta(minutes=2), 50.0)))  # late tick

    def test_bar_close_detector(self) -> None:
        detector = BarCloseDetector()
        forming = Candle("NQ", T0, M5, 10, 11, 9, 10)
        updated = Candle("NQ", T0, M5, 10, 12, 9, 11)
        self.assertIsNone(detector.update(forming))
        self.assertIsNone(detector.update(updated))
        self.assertEqual(detector.update(Candle("NQ", T0 + M5, M5, 11, 11, 11, 11)), updated)


class EmaCrossTests(unittest.TestCase):
    def strategy(self, **kwargs: object) -> EmaCrossStrategy:
        return EmaCrossStrategy(["NQ"], M5, fast=3, slow=6, atr_period=3, **kwargs)  # type: ignore[arg-type]

    def run_bars(self, strategy: EmaCrossStrategy, bars: Sequence[Candle]) -> list[Signal]:
        return [s for s in (strategy.process_candle(b) for b in bars) if s is not None]

    def test_long_on_upward_cross_with_atr_bracket(self) -> None:
        strategy = self.strategy(atr_stop_mult=2.0, reward_risk=1.5)
        signals = self.run_bars(strategy, candles("NQ", v_shape(15, 10)))
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.side, Side.LONG)
        self.assertEqual(signal.strategy, "ema_cross")
        self.assertIn("crossed above", signal.reason)
        assert signal.stop is not None and signal.take_profit is not None
        distance = signal.price - signal.stop
        self.assertGreater(distance, 0)
        self.assertAlmostEqual(signal.take_profit - signal.price, distance * 1.5)
        self.assertEqual(signal.time.minute % 5, 0)  # stamped at bar close

    def test_short_then_long_on_zigzag(self) -> None:
        closes = [20000 + 10 * i for i in range(12)] + [20110 - 10 * i for i in range(12)] \
            + [19990 + 10 * i for i in range(12)]
        sides = [s.side for s in self.run_bars(self.strategy(), candles("NQ", closes))]
        self.assertEqual(sides, [Side.SHORT, Side.LONG])

    def test_flat_instead_of_short_when_shorting_disabled(self) -> None:
        closes = [20000 + 10 * i for i in range(12)] + [20110 - 10 * i for i in range(12)]
        signals = self.run_bars(self.strategy(allow_short=False), candles("NQ", closes))
        self.assertEqual([s.side for s in signals], [Side.FLAT])
        self.assertIsNone(signals[0].stop)

    def test_no_signal_during_warmup_or_trend(self) -> None:
        strategy = self.strategy()
        self.assertEqual(strategy.warmup_bars, 7)
        rising = candles("NQ", [20000 + 5 * i for i in range(40)])
        self.assertEqual(self.run_bars(strategy, rising), [])

    def test_duplicates_other_symbols_and_timeframes_are_ignored(self) -> None:
        strategy = self.strategy()
        bars = candles("NQ", v_shape(15, 10))
        replayed = bars[:20] + bars[5:20] + bars[20:]  # a reconnect replays old bars
        noise = candles("BTCUSDT", v_shape(15, 10)) + [
            Candle("NQ", T0, timedelta(minutes=1), 1, 1, 1, 1)]
        signals = self.run_bars(strategy, replayed + noise)
        self.assertEqual(len(signals), 1)

    def test_symbols_are_independent(self) -> None:
        strategy = EmaCrossStrategy(["NQ", "BTCUSDT"], M5, fast=3, slow=6, atr_period=3)
        nq = candles("NQ", v_shape(15, 10))
        btc = candles("BTCUSDT", [60000 + 20 * i for i in range(25)])
        interleaved = [bar for pair in zip(nq, btc) for bar in pair]
        signals = self.run_bars(strategy, interleaved)
        self.assertEqual([(s.symbol, s.side) for s in signals], [("NQ", Side.LONG)])

    def test_ticks_build_bars_for_the_strategy(self) -> None:
        strategy = self.strategy()
        signals: list[Signal] = []
        for bar in candles("NQ", v_shape(15, 10)) + candles("NQ", [20000], start=T0 + 25 * M5):
            for offset, price in ((0, bar.open), (1, bar.high), (2, bar.low), (4, bar.close)):
                signals += strategy.process_tick(Tick("NQ", bar.start + timedelta(minutes=offset), price, 1))
        self.assertEqual([s.side for s in signals], [Side.LONG])

    def test_bad_parameters(self) -> None:
        with self.assertRaises(ValueError):
            EmaCrossStrategy(["NQ"], M5, fast=10, slow=5)
        with self.assertRaises(ValueError):
            EmaCrossStrategy([], M5)


if __name__ == "__main__":
    unittest.main()
