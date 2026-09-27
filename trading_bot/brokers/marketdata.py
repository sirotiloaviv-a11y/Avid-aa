"""Market data feeds. Each feed pushes *closed* candles to a sink callback.

* :class:`SimulatedFeed`: random-walk bars for paper trading with no data
  subscription (e.g. NQ without a Tradovate market-data login).
* :class:`ReplayFeed`: plays a fixed list of bars (tests, demos, CSV files).
* Venue feeds: :class:`~.bybit.BybitKlineFeed`, :class:`~.tradovate.TradovateChartFeed`.
"""

from __future__ import annotations

import csv
import math
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from ..strategies.candles import bar_start
from ..strategies.models import Candle
from ..utils.logger import get_logger
from ..utils.time_utils import utc_now

log = get_logger(__name__)

CandleSink = Callable[[Candle], None]


class MarketDataFeed(Protocol):
    @property
    def connected(self) -> bool: ...
    def start(self, sink: CandleSink) -> None: ...
    def stop(self) -> None: ...


# Rough per-bar volatility defaults for the simulator (fraction of price).
SIM_START: dict[str, float] = {"NQ": 20000.0, "MNQ": 20000.0, "BTCUSDT": 60000.0, "ETHUSDT": 3000.0}
SIM_VOL: dict[str, float] = {"NQ": 0.0012, "MNQ": 0.0012, "BTCUSDT": 0.002, "ETHUSDT": 0.0025}


class SimulatedFeed:
    """Geometric random walk, one bar per ``interval`` seconds of wall time.

    Bars are stamped on the real clock (the bar that just ended), so the
    risk engine, news guard and dashboard behave exactly as with live data.
    """

    def __init__(
        self,
        symbols: Sequence[str],
        timeframe: timedelta,
        *,
        interval: float | None = None,
        seed: int | None = None,
        start_prices: Mapping[str, float] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.symbols = list(symbols)
        self.timeframe = timeframe
        self.interval = interval if interval is not None else timeframe.total_seconds()
        self._rng = random.Random(seed)
        self._prices = {s: (start_prices or {}).get(s, SIM_START.get(s, 100.0)) for s in self.symbols}
        self._clock = clock
        self._last_start: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def next_bars(self, end: datetime) -> list[Candle]:
        start = bar_start(end, self.timeframe) - self.timeframe
        # A demo running faster than real time still needs distinct bar times.
        if self._last_start is not None and start <= self._last_start:
            start = self._last_start + self.timeframe
        self._last_start = start
        bars: list[Candle] = []
        for symbol in self.symbols:
            vol = SIM_VOL.get(symbol, 0.002)
            open_ = self._prices[symbol]
            path = [open_]
            for _ in range(4):
                path.append(path[-1] * math.exp(self._rng.gauss(0, vol / 2)))
            close = path[-1]
            self._prices[symbol] = close
            bars.append(Candle(symbol, start, self.timeframe, open_, max(path), min(path), close,
                               self._rng.uniform(100, 1000)))
        return bars

    def start(self, sink: CandleSink) -> None:
        def run() -> None:
            while not self._stop.wait(self.interval):
                for bar in self.next_bars(self._clock()):
                    sink(bar)

        self._stop.clear()
        self._thread = threading.Thread(target=run, name="feed-simulated", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None


class ReplayFeed:
    """Plays bars in order, ``delay`` seconds apart, then stops."""

    def __init__(self, candles: Iterable[Candle], *, delay: float = 0.0) -> None:
        self.candles = sorted(candles, key=lambda c: (c.start, c.symbol))
        self.delay = delay
        self.done = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return not self.done.is_set()

    def start(self, sink: CandleSink) -> None:
        def run() -> None:
            for candle in self.candles:
                if self._stop.is_set():
                    break
                sink(candle)
                if self.delay and self._stop.wait(self.delay):
                    break
            self.done.set()

        self._thread = threading.Thread(target=run, name="feed-replay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    @classmethod
    def from_csv(cls, path: Path, timeframe: timedelta, *, delay: float = 0.0) -> ReplayFeed:
        """CSV columns: ``symbol,start,open,high,low,close[,volume]`` (start: ISO-8601, UTC)."""
        candles: list[Candle] = []
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                start = datetime.fromisoformat(row["start"].replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                candles.append(Candle(row["symbol"].upper(), start, timeframe, float(row["open"]),
                                      float(row["high"]), float(row["low"]), float(row["close"]),
                                      float(row.get("volume") or 0)))
        return cls(candles, delay=delay)


class CompositeFeed:
    """Several feeds behind one interface (e.g. Bybit for crypto + simulated NQ)."""

    def __init__(self, feeds: Sequence[MarketDataFeed]) -> None:
        self.feeds = list(feeds)

    @property
    def connected(self) -> bool:
        return all(f.connected for f in self.feeds)

    def start(self, sink: CandleSink) -> None:
        for feed in self.feeds:
            feed.start(sink)

    def stop(self) -> None:
        for feed in self.feeds:
            try:
                feed.stop()
            except Exception:
                log.exception("Stopping feed %r failed", feed)
