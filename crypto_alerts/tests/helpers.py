"""Shared fixtures: synthetic candle series with a known setup on the last candle."""

from __future__ import annotations

from crypto_alerts.config import IndicatorSettings, StrategySettings
from crypto_alerts.market_data import Candle

TF_MS = 15 * 60_000

# Short periods so a ~40-candle series has every indicator warmed up.
INDICATORS = IndicatorSettings(
    rsi_period=14, atr_period=14, volume_ma_period=20, fast_ma_period=10, slow_ma_period=20, swing_width=3
)
STRATEGY = StrategySettings(sr_lookback=30)


def _candles(rows: list[tuple[float, float, float, float, float]]) -> list[Candle]:
    return [Candle(i * TF_MS, o, h, l, c, v) for i, (o, h, l, c, v) in enumerate(rows)]


def long_setup_rows(signal_volume: float = 400.0) -> list[tuple[float, float, float, float, float]]:
    """Decline to a swing low at 99.8, bounce, sell off back into it on volume.

    The last candle gaps down, wicks to 99.95 (just above the 99.8 swing low),
    and closes green at 100.0 — below the prior close, so RSI stays oversold.
    """
    path = [110 - 0.5 * k for k in range(21)]           # 110 -> 100
    path += [100.5 + 0.6 * k for k in range(1, 8)]      # bounce to ~104.7
    path += [104.7 - 0.45 * k for k in range(1, 11)]    # back down to ~100.2
    rows, prev = [], path[0]
    for close in path:
        o = prev
        rows.append((o, max(o, close) + 0.2, min(o, close) - 0.2, close, 100.0))
        prev = close
    o = prev - 0.5
    rows.append((o, o + 0.6, 99.95, o + 0.3, signal_volume))
    return rows


def long_setup(signal_volume: float = 400.0) -> list[Candle]:
    return _candles(long_setup_rows(signal_volume))


def short_setup() -> list[Candle]:
    """The long setup mirrored around 105: overbought rejection at a swing high."""
    mirrored = [(210 - o, 210 - l, 210 - h, 210 - c, v) for o, h, l, c, v in long_setup_rows()]
    return _candles(mirrored)


def as_rows(candles: list[Candle]) -> list[list[float]]:
    """Candles in ccxt's [ts, o, h, l, c, v] row format."""
    return [[c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in candles]


def make_book(mid: float, depth_units: float, spread_pct: float = 0.01, levels: int = 20,
              step_pct: float = 0.01, symbol: str = "BTC/USDT"):
    """Symmetric order book: ``levels`` evenly sized levels per side, ``step_pct`` apart."""
    from crypto_alerts.market_data import OrderBook

    half, step, amount = mid * spread_pct / 200, mid * step_pct / 100, depth_units / levels
    asks = tuple((mid + half + k * step, amount) for k in range(levels))
    bids = tuple((mid - half - k * step, amount) for k in range(levels))
    return OrderBook(symbol, bids, asks)
