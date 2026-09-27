"""Incremental indicators: one ``update`` per closed bar, O(1) each."""

from __future__ import annotations


class EMA:
    """Exponential moving average, seeded with the SMA of the first ``period`` values."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value: float | None = None
        self._seed: list[float] = []

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
                self._seed.clear()
            return self.value
        self.value += self.alpha * (x - self.value)
        return self.value


class ATR:
    """Average True Range with Wilder smoothing."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.value: float | None = None
        self._prev_close: float | None = None
        self._seed: list[float] = []

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        if self.value is None:
            self._seed.append(true_range)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
                self._seed.clear()
            return self.value
        self.value = (self.value * (self.period - 1) + true_range) / self.period
        return self.value
