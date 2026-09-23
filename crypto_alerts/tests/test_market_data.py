"""Candle buffer and feed tests. The exchange is a stub — no ccxt, no network."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from crypto_alerts.config import ExchangeSettings
from crypto_alerts.market_data import CandleBuffer, FatalFeedError, MarketDataFeed

TF = 900_000


def row(i: int, close: float = 100.0) -> list[float]:
    return [i * TF, close, close + 1, close - 1, close, 10.0]


class CandleBufferTests(unittest.TestCase):
    def test_initial_load_is_not_a_new_close(self):
        buf = CandleBuffer(maxlen=10)
        self.assertFalse(buf.load([row(0), row(1), row(2)]))
        # The last row is the forming candle.
        self.assertEqual([c.timestamp for c in buf.closed()], [0, TF])

    def test_update_of_forming_candle_is_not_a_close(self):
        buf = CandleBuffer(maxlen=10)
        buf.load([row(0), row(1)])
        self.assertFalse(buf.update([row(1, close=101)]))

    def test_new_candle_closes_the_previous_one(self):
        buf = CandleBuffer(maxlen=10)
        buf.load([row(0), row(1)])
        buf.update([row(1, close=101)])
        self.assertTrue(buf.update([row(1, close=102), row(2)]))
        closed = buf.closed()
        self.assertEqual(closed[-1].timestamp, TF)
        self.assertEqual(closed[-1].close, 102)  # final values, not a stale update
        self.assertFalse(buf.update([row(2, close=99)]))

    def test_reload_after_gap_reports_close_missed_while_disconnected(self):
        buf = CandleBuffer(maxlen=10)
        buf.load([row(0), row(1)])
        self.assertTrue(buf.load([row(0), row(1), row(2), row(3)]))

    def test_window_is_bounded(self):
        buf = CandleBuffer(maxlen=5)
        buf.load([row(i) for i in range(20)])
        self.assertEqual(len(buf.closed()), 5)
        self.assertEqual(buf.closed()[-1].timestamp, 18 * TF)


class FakeExchange:
    """Replays scripted watch_ohlcv results; an Exception item is raised."""

    has = {"watchOHLCV": True}
    timeframes = {"15m": "15m"}

    def __init__(self, watch_script, history):
        self.markets = {"BTC/USDT": {"symbol": "BTC/USDT"}, "ETH/USD": {"inverse": True}}
        self._watch = list(watch_script)
        self._history = history
        self.fetch_calls = 0

    async def load_markets(self):
        return self.markets

    async def fetch_ohlcv(self, symbol, timeframe, limit=None):
        self.fetch_calls += 1
        return self._history

    async def watch_ohlcv(self, symbol, timeframe):
        if not self._watch:
            await asyncio.sleep(3600)
        item = self._watch.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def amount_to_precision(self, symbol, amount):
        return f"{int(amount * 1000) / 1000:.3f}"

    async def close(self):
        pass


def settings(**overrides) -> ExchangeSettings:
    base = dict(symbols=("BTC/USDT", "ETH/USD", "DOGE/XYZ"), history_candles=50, stream_timeout_seconds=10)
    base.update(overrides)
    return ExchangeSettings(**base)


class FeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Backoff sleeps would slow the suite; the logic, not the waiting, is under test.
        patcher = mock.patch("crypto_alerts.market_data.asyncio.sleep", new=self._fast_sleep)
        self._real_sleep = asyncio.sleep
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _fast_sleep(self, delay, *args):
        await self._real_sleep(0 if delay < 3600 else 3600)

    async def test_connect_filters_unknown_and_inverse_symbols(self):
        feed = MarketDataFeed(settings(), exchange=FakeExchange([], []))
        self.assertEqual(await feed.connect(), ["BTC/USDT"])
        self.assertTrue(feed.streaming)

    async def test_yields_on_close_and_recovers_from_network_error(self):
        history = [row(0), row(1)]
        exchange = FakeExchange(
            [
                [row(1, close=101)],       # forming candle update — no yield
                ConnectionError("reset"),  # network drop — reconnect + backfill
                [row(1, close=102), row(2)],  # candle 1 closes
            ],
            history,
        )
        feed = MarketDataFeed(settings(), exchange=exchange)
        stream = feed.stream_closed_candles("BTC/USDT")
        closed = await asyncio.wait_for(stream.__anext__(), timeout=5)
        self.assertEqual(closed[-1].timestamp, TF)
        self.assertEqual(exchange.fetch_calls, 2)  # initial backfill + one after the error
        await stream.aclose()

    async def test_fatal_error_is_raised(self):
        class BadSymbol(Exception):
            pass

        exchange = FakeExchange([BadSymbol("delisted")], [row(0), row(1)])
        feed = MarketDataFeed(settings(), exchange=exchange)
        feed._fatal = (BadSymbol,)
        with self.assertRaises(FatalFeedError):
            await asyncio.wait_for(feed.stream_closed_candles("BTC/USDT").__anext__(), timeout=5)

    async def test_round_amount_truncates(self):
        feed = MarketDataFeed(settings(), exchange=FakeExchange([], []))
        self.assertAlmostEqual(feed.round_amount("BTC/USDT", 1.23456), 1.234)

    async def test_round_amount_through_contract_size(self):
        exchange = FakeExchange([], [])
        exchange.markets["X/USDT:USDT"] = {"contract": True, "contractSize": 10}
        feed = MarketDataFeed(settings(), exchange=exchange)
        # 12.3456 base units = 1.23456 contracts -> 1.234 contracts -> 12.34 base.
        self.assertAlmostEqual(feed.round_amount("X/USDT:USDT", 12.3456), 12.34)

    def test_is_stale(self):
        feed = MarketDataFeed(settings(), exchange=FakeExchange([], []))
        candle = CandleBuffer(1)
        candle.load([row(0), row(1)])
        c = candle.closed()[0]
        self.assertFalse(feed.is_stale(c, now_ms=TF + 1000))
        self.assertTrue(feed.is_stale(c, now_ms=3 * TF))


if __name__ == "__main__":
    unittest.main()
