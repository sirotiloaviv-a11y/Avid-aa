"""Technical indicators over a candle window.

Pure Python on purpose: a 300-candle window is computed in well under a
millisecond, and staying off pandas/numpy keeps the install small and the
maths readable. Every series is aligned with the input candles; positions
without enough history hold ``None`` rather than a misleading number.

RSI and ATR use Wilder's smoothing, which is what TradingView and most
exchanges display, so the values in an alert match the chart you open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .config import IndicatorSettings
from .market_data import Candle

Series = list[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    """Simple moving average."""
    out: Series = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """Exponential moving average, seeded with the SMA of the first ``period`` values."""
    out: Series = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def rsi(closes: Sequence[float], period: int = 14) -> Series:
    """Relative Strength Index with Wilder's smoothing."""
    out: Series = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    out = []
    for i in range(len(highs)):
        if i == 0:
            out.append(highs[0] - lows[0])
        else:
            prev = closes[i - 1]
            out.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return out


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Series:
    """Average True Range with Wilder's smoothing."""
    tr = true_range(highs, lows, closes)
    out: Series = [None] * len(tr)
    if len(tr) < period:
        return out
    current = sum(tr[:period]) / period
    out[period - 1] = current
    for i in range(period, len(tr)):
        current = (current * (period - 1) + tr[i]) / period
        out[i] = current
    return out


def volume_ratio(volumes: Sequence[float], period: int = 20) -> Series:
    """Each candle's volume divided by the average of the ``period`` candles *before* it.

    Excluding the current candle from its own baseline matters: otherwise a
    large spike inflates the average it is compared against and a true 3x
    surge reads as roughly 2.7x.
    """
    out: Series = [None] * len(volumes)
    for i in range(period, len(volumes)):
        baseline = sum(volumes[i - period : i]) / period
        out[i] = volumes[i] / baseline if baseline > 0 else None
    return out


def swing_lows(lows: Sequence[float], width: int) -> list[int]:
    """Indices of confirmed swing lows: strictly below the ``width`` candles to the
    left and at or below the ``width`` candles to the right.

    A swing is only confirmed once ``width`` candles have closed after it, so
    the last ``width`` candles can never be swings — no look-ahead.
    """
    return [
        i
        for i in range(width, len(lows) - width)
        if lows[i] < min(lows[i - width : i]) and lows[i] <= min(lows[i + 1 : i + width + 1])
    ]


def swing_highs(highs: Sequence[float], width: int) -> list[int]:
    """Mirror of :func:`swing_lows` for highs."""
    return [
        i
        for i in range(width, len(highs) - width)
        if highs[i] > max(highs[i - width : i]) and highs[i] >= max(highs[i + 1 : i + width + 1])
    ]


@dataclass(frozen=True)
class IndicatorFrame:
    """Candles plus every indicator series, index-aligned."""

    candles: tuple[Candle, ...]
    rsi: tuple[Optional[float], ...]
    atr: tuple[Optional[float], ...]
    volume_ratio: tuple[Optional[float], ...]
    fast_ma: tuple[Optional[float], ...]
    slow_ma: tuple[Optional[float], ...]
    swing_low_indices: tuple[int, ...]
    swing_high_indices: tuple[int, ...]
    settings: IndicatorSettings

    def __len__(self) -> int:
        return len(self.candles)

    @property
    def last(self) -> int:
        return len(self.candles) - 1


def compute_indicators(candles: Sequence[Candle], settings: IndicatorSettings) -> IndicatorFrame:
    """Run the full indicator pipeline over closed candles (oldest first)."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    return IndicatorFrame(
        candles=tuple(candles),
        rsi=tuple(rsi(closes, settings.rsi_period)),
        atr=tuple(atr(highs, lows, closes, settings.atr_period)),
        volume_ratio=tuple(volume_ratio(volumes, settings.volume_ma_period)),
        fast_ma=tuple(ema(closes, settings.fast_ma_period)),
        slow_ma=tuple(ema(closes, settings.slow_ma_period)),
        swing_low_indices=tuple(swing_lows(lows, settings.swing_width)),
        swing_high_indices=tuple(swing_highs(highs, settings.swing_width)),
        settings=settings,
    )
