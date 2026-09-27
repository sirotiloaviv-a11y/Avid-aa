"""EMA crossover with ATR-based stop and fixed reward:risk target.

* Fast EMA crosses above slow EMA -> LONG, stop ``atr_stop_mult`` ATRs below
  the close, target ``reward_risk`` times the stop distance above it.
* Fast crosses below slow -> SHORT (mirror image), or FLAT when shorting is
  disabled.

A reference implementation of the interface, not a recommendation: validate
any strategy on historical data and a demo account before funding it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from .base import Strategy
from .indicators import ATR, EMA
from .models import Candle, Side, Signal


@dataclass
class _SymbolState:
    fast: EMA
    slow: EMA
    atr: ATR
    prev_diff: float | None = None


class EmaCrossStrategy(Strategy):
    name = "ema_cross"

    def __init__(
        self,
        symbols: Sequence[str],
        timeframe: timedelta,
        *,
        fast: int = 9,
        slow: int = 21,
        atr_period: int = 14,
        atr_stop_mult: float = 1.5,
        reward_risk: float = 2.0,
        allow_short: bool = True,
    ) -> None:
        super().__init__(symbols, timeframe)
        if not 0 < fast < slow:
            raise ValueError("need 0 < fast < slow")
        if atr_stop_mult <= 0 or reward_risk <= 0:
            raise ValueError("atr_stop_mult and reward_risk must be positive")
        self.fast, self.slow, self.atr_period = fast, slow, atr_period
        self.atr_stop_mult = atr_stop_mult
        self.reward_risk = reward_risk
        self.allow_short = allow_short
        self._state: dict[str, _SymbolState] = {}

    @property
    def warmup_bars(self) -> int:
        # The slow EMA must be seeded, then one more bar to compare against.
        return max(self.slow, self.atr_period) + 1

    def _get(self, symbol: str) -> _SymbolState:
        state = self._state.get(symbol)
        if state is None:
            state = _SymbolState(EMA(self.fast), EMA(self.slow), ATR(self.atr_period))
            self._state[symbol] = state
        return state

    def on_candle(self, candle: Candle) -> Signal | None:
        s = self._get(candle.symbol)
        fast = s.fast.update(candle.close)
        slow = s.slow.update(candle.close)
        atr = s.atr.update(candle.high, candle.low, candle.close)
        if fast is None or slow is None or atr is None:
            return None
        diff = fast - slow
        prev, s.prev_diff = s.prev_diff, diff
        if prev is None or atr <= 0:
            return None

        crossed_up = prev <= 0 < diff
        crossed_down = prev >= 0 > diff
        if not (crossed_up or crossed_down):
            return None
        distance = atr * self.atr_stop_mult
        price = candle.close
        reason = f"EMA{self.fast} crossed {'above' if crossed_up else 'below'} EMA{self.slow}"
        if crossed_up:
            return Signal(self.name, candle.symbol, Side.LONG, candle.end, price,
                          stop=price - distance, take_profit=price + distance * self.reward_risk,
                          reason=reason)
        if not self.allow_short:
            return Signal(self.name, candle.symbol, Side.FLAT, candle.end, price, reason=reason)
        return Signal(self.name, candle.symbol, Side.SHORT, candle.end, price,
                      stop=price + distance, take_profit=price - distance * self.reward_risk,
                      reason=reason)
