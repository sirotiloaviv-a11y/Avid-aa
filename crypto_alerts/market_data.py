"""Exchange connectivity and the closed-candle stream.

The feed backfills history over REST, then follows the forming candle over a
websocket (ccxt.pro ``watch_ohlcv``) or, if websockets are disabled or not
supported, by polling ``fetch_ohlcv``. Either way it yields only when a candle
*closes*, so the strategy never evaluates a bar whose RSI and volume are still
moving — the most common source of alerts that "disappear" a minute later.

Network failures never escape the stream: it backs off, reconnects, backfills
again so indicators are not computed across a hole, and carries on. Only
errors that retrying cannot fix (unknown symbol, bad API key) are raised.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Sequence

from .config import ExchangeSettings, parse_timeframe

log = logging.getLogger(__name__)


class FatalFeedError(RuntimeError):
    """An error that retrying will not fix; the symbol should stop being monitored."""


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: int  # open time, milliseconds since the epoch (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ccxt(cls, row: Sequence[Any]) -> "Candle":
        ts, o, h, l, c, v = row[:6]
        return cls(int(ts), float(o), float(h), float(l), float(c), float(v or 0.0))


class CandleBuffer:
    """Rolling OHLCV window that knows which candles are closed.

    A candle is closed once a candle with a later open time exists. That rule
    works identically for websocket updates and REST polls, and does not
    depend on the local clock being in sync with the exchange.
    """

    def __init__(self, maxlen: int) -> None:
        self._maxlen = maxlen
        self._candles: dict[int, Candle] = {}
        self._last_closed_ts: int | None = None

    def load(self, rows: Iterable[Sequence[Any]]) -> bool:
        """Replace the window with a fresh backfill.

        The first load never reports a new close — history is not actionable.
        A reload after a reconnect does, if a candle closed while disconnected.
        """
        self._candles = {}
        self._ingest(rows)
        return self._advance()

    def update(self, rows: Iterable[Sequence[Any]]) -> bool:
        """Merge new rows. Returns True if a new candle has closed since the last call."""
        self._ingest(rows)
        return self._advance()

    def closed(self) -> list[Candle]:
        """Closed candles, oldest first (the forming candle is excluded)."""
        ordered = sorted(self._candles)
        return [self._candles[ts] for ts in ordered[:-1]]

    @property
    def last_closed_timestamp(self) -> int | None:
        return self._last_closed_ts

    def _ingest(self, rows: Iterable[Sequence[Any]]) -> None:
        for row in rows:
            candle = Candle.from_ccxt(row)
            self._candles[candle.timestamp] = candle
        if len(self._candles) > self._maxlen + 1:
            for ts in sorted(self._candles)[: len(self._candles) - self._maxlen - 1]:
                del self._candles[ts]

    def _advance(self) -> bool:
        if len(self._candles) < 2:
            return False
        newest_closed = sorted(self._candles)[-2]
        if self._last_closed_ts is None:
            self._last_closed_ts = newest_closed
            return False
        if newest_closed > self._last_closed_ts:
            self._last_closed_ts = newest_closed
            return True
        return False


class Backoff:
    """Exponential backoff with jitter: 1s, 2s, 4s ... capped, reset on success."""

    def __init__(self, base: float = 1.0, cap: float = 60.0) -> None:
        self.base, self.cap = base, cap
        self.attempt = 0

    def next_delay(self) -> float:
        delay = min(self.cap, self.base * 2**self.attempt)
        self.attempt += 1
        return delay * random.uniform(0.8, 1.2)

    def reset(self) -> None:
        self.attempt = 0

    async def sleep(self) -> None:
        await asyncio.sleep(self.next_delay())


def _fatal_exception_types() -> tuple[type[BaseException], ...]:
    try:
        import ccxt
    except ImportError:  # tests run without ccxt installed
        return ()
    return (ccxt.BadSymbol, ccxt.AuthenticationError, ccxt.PermissionDenied, ccxt.NotSupported)


def create_exchange(settings: ExchangeSettings) -> Any:
    """Instantiate a ccxt.pro exchange (websockets), or async REST ccxt as a fallback."""
    try:
        import ccxt.async_support as ccxt_async
    except ImportError as exc:
        raise FatalFeedError("ccxt is not installed: pip install -r crypto_alerts/requirements.txt") from exc

    params: dict[str, Any] = {
        "enableRateLimit": True,
        "options": {"defaultType": settings.market_type},
    }
    if settings.api_key:
        params["apiKey"] = settings.api_key
        params["secret"] = settings.api_secret

    exchange_cls = None
    if settings.use_websocket:
        try:
            import ccxt.pro as ccxt_pro

            exchange_cls = getattr(ccxt_pro, settings.exchange_id, None)
        except ImportError:
            exchange_cls = None
        if exchange_cls is None:
            log.warning("No websocket support for %s; falling back to REST polling", settings.exchange_id)
    if exchange_cls is None:
        exchange_cls = getattr(ccxt_async, settings.exchange_id, None)
    if exchange_cls is None:
        raise FatalFeedError(f"Unknown exchange {settings.exchange_id!r}")

    exchange = exchange_cls(params)
    if settings.sandbox:
        exchange.set_sandbox_mode(True)
    return exchange


class MarketDataFeed:
    """One exchange connection shared by every monitored symbol."""

    def __init__(self, settings: ExchangeSettings, exchange: Any | None = None) -> None:
        self.settings = settings
        self._exchange = exchange
        self._timeframe_ms = parse_timeframe(settings.timeframe) * 1000
        self._fatal = _fatal_exception_types()

    @property
    def exchange(self) -> Any:
        if self._exchange is None:
            self._exchange = create_exchange(self.settings)
        return self._exchange

    @property
    def timeframe_ms(self) -> int:
        return self._timeframe_ms

    @property
    def streaming(self) -> bool:
        has = getattr(self.exchange, "has", {}) or {}
        return self.settings.use_websocket and bool(has.get("watchOHLCV"))

    async def connect(self) -> list[str]:
        """Load markets and return the configured symbols that exist on the exchange.

        Unknown symbols are logged and dropped rather than failing the whole
        process. Network errors are retried until markets load.
        """
        exchange = self.exchange  # creation errors (ccxt missing, unknown id) are fatal, not retried
        backoff = Backoff()
        while True:
            try:
                await exchange.load_markets()
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._fatal and isinstance(exc, self._fatal):
                    raise FatalFeedError(f"{self.settings.exchange_id}: {exc}") from exc
                delay = backoff.next_delay()
                log.warning("load_markets failed (%s); retrying in %.0fs", exc, delay)
                await asyncio.sleep(delay)

        timeframes = getattr(self.exchange, "timeframes", None) or {}
        if timeframes and self.settings.timeframe not in timeframes:
            raise FatalFeedError(
                f"{self.settings.exchange_id} does not support timeframe {self.settings.timeframe}"
            )

        markets = getattr(self.exchange, "markets", None) or {}
        valid = []
        for symbol in self.settings.symbols:
            market = markets.get(symbol)
            if market is None:
                log.error("Symbol %s not found on %s — skipping", symbol, self.settings.exchange_id)
            elif market.get("inverse"):
                log.error("Symbol %s is an inverse (coin-margined) contract — not supported, skipping", symbol)
            else:
                valid.append(symbol)
        mode = "websocket" if self.streaming else f"REST polling every {self.settings.poll_interval_seconds:.0f}s"
        log.info("Connected to %s (%s) — %d symbol(s)", self.settings.exchange_id, mode, len(valid))
        return valid

    async def stream_closed_candles(self, symbol: str) -> AsyncIterator[list[Candle]]:
        """Yield the closed-candle history each time a new candle closes on ``symbol``."""
        buffer = CandleBuffer(maxlen=self.settings.history_candles)
        backoff = Backoff()
        while True:
            try:
                rows = await self.exchange.fetch_ohlcv(
                    symbol, self.settings.timeframe, limit=self.settings.history_candles + 1
                )
                if buffer.load(rows):
                    yield buffer.closed()
                backoff.reset()
                while True:
                    rows = await self._next_rows(symbol)
                    backoff.reset()
                    if buffer.update(rows):
                        yield buffer.closed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._fatal and isinstance(exc, self._fatal):
                    raise FatalFeedError(f"{symbol}: {exc}") from exc
                delay = backoff.next_delay()
                reason = "stream stalled" if isinstance(exc, asyncio.TimeoutError) else repr(exc)
                log.warning("%s feed error (%s); reconnecting in %.1fs", symbol, reason, delay)
                await asyncio.sleep(delay)

    async def _next_rows(self, symbol: str) -> list[Sequence[Any]]:
        if self.streaming:
            return await asyncio.wait_for(
                self.exchange.watch_ohlcv(symbol, self.settings.timeframe),
                timeout=self.settings.stream_timeout_seconds,
            )
        await asyncio.sleep(self.settings.poll_interval_seconds)
        return await self.exchange.fetch_ohlcv(symbol, self.settings.timeframe, limit=3)

    def round_amount(self, symbol: str, units: float) -> float:
        """Round a base-currency quantity *down* to what the exchange accepts.

        Rounding down keeps the loss at the stop at or below the risk budget.
        Contract markets are converted through their contract size.
        """
        markets = getattr(self.exchange, "markets", None) or {}
        market = markets.get(symbol) or {}
        contract_size = float(market.get("contractSize") or 1.0) if market.get("contract") else 1.0
        try:
            amount = float(self.exchange.amount_to_precision(symbol, units / contract_size))
        except Exception as exc:
            # ccxt raises InvalidOrder when the amount is below one lot step.
            if type(exc).__name__ == "InvalidOrder":
                return 0.0
            log.debug("amount_to_precision(%s, %s) failed, using unrounded size: %s", symbol, units, exc)
            return units
        return amount * contract_size

    def is_stale(self, candle: Candle, now_ms: int | None = None) -> bool:
        """True if ``candle`` closed more than one full timeframe ago."""
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        closed_at = candle.timestamp + self._timeframe_ms
        return now_ms - closed_at > self._timeframe_ms

    async def close(self) -> None:
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception as exc:
                log.debug("exchange.close() failed: %s", exc)
