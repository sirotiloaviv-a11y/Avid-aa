"""The strategy interface.

A strategy sees closed candles (and optionally ticks) and says what it wants
to be on each symbol: LONG, SHORT or FLAT. It never sizes positions, checks
limits or talks to brokers; the execution engine does that, through the risk
engine, for every account.

Strategies are deterministic functions of the bars they have seen, which is
what makes them unit-testable bar by bar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Sequence

from .candles import CandleBuilder
from .models import Candle, Signal, Tick


class Strategy(ABC):
    name: str = "strategy"

    def __init__(self, symbols: Sequence[str], timeframe: timedelta) -> None:
        if not symbols:
            raise ValueError("a strategy needs at least one symbol")
        self.symbols = tuple(s.upper() for s in symbols)
        self.timeframe = timeframe
        self._last_bar: dict[str, datetime] = {}
        self._builder = CandleBuilder(timeframe)

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Bars needed before the first signal can fire."""

    @abstractmethod
    def on_candle(self, candle: Candle) -> Signal | None:
        """Called once per closed bar, in time order, per symbol."""

    def on_tick(self, tick: Tick) -> Signal | None:  # noqa: ARG002 - optional hook
        """Optional intrabar hook. Default: no tick-level logic."""
        return None

    # ----------------------------------------------------------- plumbing
    def process_candle(self, candle: Candle) -> Signal | None:
        """Feed a bar, ignoring other symbols, other timeframes and replays.

        After a WebSocket reconnect a feed may resend bars it already sent;
        a strategy must never see the same bar twice.
        """
        if candle.symbol not in self.symbols or candle.timeframe != self.timeframe:
            return None
        last = self._last_bar.get(candle.symbol)
        if last is not None and candle.start <= last:
            return None
        self._last_bar[candle.symbol] = candle.start
        return self.on_candle(candle)

    def process_tick(self, tick: Tick) -> list[Signal]:
        """Tick-only feeds: build bars, and give the strategy its tick hook."""
        if tick.symbol not in self.symbols:
            return []
        signals: list[Signal] = []
        closed = self._builder.add(tick)
        if closed is not None:
            signal = self.process_candle(closed)
            if signal is not None:
                signals.append(signal)
        signal = self.on_tick(tick)
        if signal is not None:
            signals.append(signal)
        return signals
