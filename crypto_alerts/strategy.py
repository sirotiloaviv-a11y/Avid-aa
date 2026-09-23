"""Signal generation.

A strategy looks at the most recent *closed* candle of an indicator frame and
either returns a :class:`Signal` or ``None``. It decides *whether* and *why*
to trade; where the stop goes and how big the position is belongs to the risk
manager. New strategies subclass :class:`Strategy` and implement ``evaluate``.

The bundled template, :class:`RsiVolumeReversalStrategy`, is a mean-reversion
setup:

* LONG  — RSI oversold, a volume spike, and the candle wicks into a prior
  swing low (support) and closes back above it with a bullish reaction.
* SHORT — RSI overbought, a volume spike, and the candle wicks into a prior
  swing high (resistance) and closes back below it with a bearish reaction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import StrategySettings
from .indicators import IndicatorFrame
from .market_data import Candle

log = logging.getLogger(__name__)


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class Signal:
    symbol: str
    timeframe: str
    direction: Direction
    strategy: str
    candle: Candle  # the closed candle that triggered the signal
    entry_price: float
    atr: float
    rsi: float
    volume_ratio: float
    # The support/resistance level that was tested.
    key_level: float
    # Where the setup is structurally wrong: the lower of the wick and the
    # support for a long, the higher of the wick and resistance for a short.
    invalidation_level: float
    reasons: tuple[str, ...]
    # One-line trigger summary, e.g. "RSI oversold + 3.1x Volume Surge + Support bounce".
    summary: str = ""
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None


class Strategy(ABC):
    """Base class for all strategies."""

    name: str = "strategy"

    @abstractmethod
    def evaluate(self, symbol: str, timeframe: str, frame: IndicatorFrame) -> Optional[Signal]:
        """Return a signal for the last closed candle in ``frame``, or None."""


def _bullish_reaction(c: Candle) -> bool:
    """Green close, or a lower wick at least half the candle's range (hammer-like)."""
    rng = c.high - c.low
    if rng <= 0:
        return False
    return c.close > c.open or (min(c.open, c.close) - c.low) >= 0.5 * rng


def _bearish_reaction(c: Candle) -> bool:
    """Red close, or an upper wick at least half the candle's range (shooting-star-like)."""
    rng = c.high - c.low
    if rng <= 0:
        return False
    return c.close < c.open or (c.high - max(c.open, c.close)) >= 0.5 * rng


def _fmt(value: float) -> str:
    return f"{value:,.{2 if value >= 1 else 6}f}"


class RsiVolumeReversalStrategy(Strategy):
    name = "RSI + Volume Reversal"

    def __init__(self, settings: StrategySettings) -> None:
        self.settings = settings

    def evaluate(self, symbol: str, timeframe: str, frame: IndicatorFrame) -> Optional[Signal]:
        i = frame.last
        if i < 1:
            return None
        candle = frame.candles[i]
        atr, vol_ratio = frame.atr[i], frame.volume_ratio[i]
        recent_rsi = [
            value
            for value in frame.rsi[max(0, i - self.settings.rsi_lookback + 1) : i + 1]
            if value is not None
        ]
        current_rsi = frame.rsi[i]
        if atr is None or atr <= 0 or vol_ratio is None or current_rsi is None or not recent_rsi:
            return None

        volume_ok = vol_ratio >= self.settings.volume_spike_multiplier
        tolerance = self.settings.sr_tolerance_atr * atr
        oldest = max(0, i - self.settings.sr_lookback)

        long_signal = self._long(symbol, timeframe, frame, i, candle, atr, current_rsi,
                                 min(recent_rsi), vol_ratio, volume_ok, tolerance, oldest)
        short_signal = self._short(symbol, timeframe, frame, i, candle, atr, current_rsi,
                                   max(recent_rsi), vol_ratio, volume_ok, tolerance, oldest)
        if long_signal and short_signal:  # only possible with a long rsi_lookback; ambiguous
            log.info("%s: long and short both triggered on the same candle — ignoring", symbol)
            return None
        return long_signal or short_signal

    def _long(self, symbol, timeframe, frame, i, candle, atr, current_rsi, extreme_rsi,
              vol_ratio, volume_ok, tolerance, oldest) -> Optional[Signal]:
        if extreme_rsi >= self.settings.rsi_oversold or not volume_ok:
            return None
        if not _bullish_reaction(candle):
            return None
        levels = [
            frame.candles[j].low
            for j in frame.swing_low_indices
            if oldest <= j < i
            and abs(candle.low - frame.candles[j].low) <= tolerance
            and candle.close > frame.candles[j].low
        ]
        if not levels:
            return None
        support = min(levels, key=lambda level: abs(candle.low - level))
        slow_ma = frame.slow_ma[i]
        if self.settings.trend_filter and slow_ma is not None and candle.close <= slow_ma:
            return None
        reasons = (
            f"RSI oversold ({extreme_rsi:.1f} < {self.settings.rsi_oversold:g})",
            f"{vol_ratio:.1f}x volume surge vs {frame.settings.volume_ma_period}-candle average",
            f"Bounce off support {_fmt(support)} (swing low)",
        )
        return Signal(
            symbol=symbol, timeframe=timeframe, direction=Direction.LONG, strategy=self.name,
            candle=candle, entry_price=candle.close, atr=atr, rsi=current_rsi,
            volume_ratio=vol_ratio, key_level=support,
            invalidation_level=min(candle.low, support), reasons=reasons,
            summary=f"RSI oversold + {vol_ratio:.1f}x Volume Surge + Support bounce",
            fast_ma=frame.fast_ma[i], slow_ma=slow_ma,
        )

    def _short(self, symbol, timeframe, frame, i, candle, atr, current_rsi, extreme_rsi,
               vol_ratio, volume_ok, tolerance, oldest) -> Optional[Signal]:
        if extreme_rsi <= self.settings.rsi_overbought or not volume_ok:
            return None
        if not _bearish_reaction(candle):
            return None
        levels = [
            frame.candles[j].high
            for j in frame.swing_high_indices
            if oldest <= j < i
            and abs(candle.high - frame.candles[j].high) <= tolerance
            and candle.close < frame.candles[j].high
        ]
        if not levels:
            return None
        resistance = min(levels, key=lambda level: abs(candle.high - level))
        slow_ma = frame.slow_ma[i]
        if self.settings.trend_filter and slow_ma is not None and candle.close >= slow_ma:
            return None
        reasons = (
            f"RSI overbought ({extreme_rsi:.1f} > {self.settings.rsi_overbought:g})",
            f"{vol_ratio:.1f}x volume surge vs {frame.settings.volume_ma_period}-candle average",
            f"Rejection at resistance {_fmt(resistance)} (swing high)",
        )
        return Signal(
            symbol=symbol, timeframe=timeframe, direction=Direction.SHORT, strategy=self.name,
            candle=candle, entry_price=candle.close, atr=atr, rsi=current_rsi,
            volume_ratio=vol_ratio, key_level=resistance,
            invalidation_level=max(candle.high, resistance), reasons=reasons,
            summary=f"RSI overbought + {vol_ratio:.1f}x Volume Surge + Resistance rejection",
            fast_ma=frame.fast_ma[i], slow_ma=slow_ma,
        )
