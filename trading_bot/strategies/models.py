"""Market data and signal types shared by strategies, feeds and brokers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


@dataclass(frozen=True)
class Tick:
    symbol: str
    time: datetime  # UTC
    price: float
    size: float = 0.0


@dataclass(frozen=True)
class Candle:
    symbol: str
    start: datetime  # UTC, bar open time
    timeframe: timedelta
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def end(self) -> datetime:
        return self.start + self.timeframe

    def __post_init__(self) -> None:
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"inconsistent OHLC for {self.symbol} at {self.start}")


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class Signal:
    """What a strategy wants: be LONG, be SHORT, or be FLAT on ``symbol``.

    ``price`` is the reference entry (the close of the bar that produced
    the signal); ``stop`` is required for LONG/SHORT, because the risk engine
    sizes every position from its stop distance.
    """

    strategy: str
    symbol: str
    side: Side
    time: datetime
    price: float
    stop: float | None = None
    take_profit: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.side is Side.FLAT:
            return
        if self.stop is None:
            raise ValueError(f"{self.side.value} signal on {self.symbol} needs a stop")
        long = self.side is Side.LONG
        if (self.stop >= self.price) if long else (self.stop <= self.price):
            raise ValueError(f"stop {self.stop} is on the wrong side of {self.price} for {self.side.value}")
        if self.take_profit is not None and ((self.take_profit <= self.price) if long else (self.take_profit >= self.price)):
            raise ValueError(f"take profit {self.take_profit} is on the wrong side for {self.side.value}")
