"""Candle construction helpers for feeds that do not deliver closed bars."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Candle, Tick

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def bar_start(ts: datetime, timeframe: timedelta) -> datetime:
    """Floor ``ts`` to the timeframe grid (UTC epoch aligned)."""
    steps = (ts - EPOCH) // timeframe
    return EPOCH + steps * timeframe


class CandleBuilder:
    """Aggregates ticks into bars; returns a bar once the next one starts."""

    def __init__(self, timeframe: timedelta) -> None:
        self.timeframe = timeframe
        self._open: dict[str, list[float]] = {}  # symbol -> [o, h, l, c, v]
        self._start: dict[str, datetime] = {}

    def add(self, tick: Tick) -> Candle | None:
        start = bar_start(tick.time, self.timeframe)
        current = self._start.get(tick.symbol)
        closed: Candle | None = None
        if current is not None and start < current:
            return None  # late tick for a bar already closed
        if current is not None and start > current:
            o, h, l, c, v = self._open[tick.symbol]
            closed = Candle(tick.symbol, current, self.timeframe, o, h, l, c, v)
            current = None
        if current is None:
            self._start[tick.symbol] = start
            self._open[tick.symbol] = [tick.price, tick.price, tick.price, tick.price, tick.size]
        else:
            bar = self._open[tick.symbol]
            bar[1] = max(bar[1], tick.price)
            bar[2] = min(bar[2], tick.price)
            bar[3] = tick.price
            bar[4] += tick.size
        return closed


class BarCloseDetector:
    """For streams that repeatedly update the *forming* bar (e.g. Tradovate
    charts): a bar is final once a bar with a later start time arrives."""

    def __init__(self) -> None:
        self._pending: dict[str, Candle] = {}

    def update(self, candle: Candle) -> Candle | None:
        pending = self._pending.get(candle.symbol)
        if pending is not None and candle.start < pending.start:
            return None  # stale update for an older bar
        self._pending[candle.symbol] = candle
        if pending is not None and candle.start > pending.start:
            return pending
        return None
