"""Sliding-window rate limiter. Single user, so one global window suffices."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> float:
        """Record a hit. Returns 0 if allowed, else seconds until a slot frees."""
        with self._lock:
            now = self._clock()
            while self._hits and now - self._hits[0] >= self.window_s:
                self._hits.popleft()
            if len(self._hits) >= self.limit:
                return self.window_s - (now - self._hits[0])
            self._hits.append(now)
            return 0.0
