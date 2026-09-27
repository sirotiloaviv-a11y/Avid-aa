"""Events the risk engine publishes to subscribers (Telegram, dashboards, ...).

Subscribers are called synchronously on the engine's thread, so they must be
fast and must not raise; the Telegram notifier only enqueues a message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Union


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    TAKE_PROFIT = "tp"
    STOP_LOSS = "sl"
    NEWS_HALT = "news_halt"
    DAILY_HALT = "daily_halt"
    MANUAL = "manual"
    OTHER = "other"


class HaltKind:
    DAILY_LOSS = "daily_loss"
    MAX_DRAWDOWN = "max_drawdown"
    MANUAL = "manual"


@dataclass(frozen=True)
class HaltEvent:
    account_id: str
    kind: str
    reason: str
    at: datetime
    should_flatten: bool


@dataclass(frozen=True)
class TradeOpenedEvent:
    account_id: str
    trade_id: str
    symbol: str
    direction: Direction | None
    entry_price: float | None
    stop_price: float | None
    take_profit: float | None
    quantity: float | None
    risk_amount: float
    # Risk as a percent of the last reported balance.
    risk_pct: float | None
    balance: float | None
    at: datetime


@dataclass(frozen=True)
class TradeClosedEvent:
    account_id: str
    trade_id: str
    symbol: str | None
    direction: Direction | None
    entry_price: float | None
    exit_price: float | None
    realized_pnl: float
    # P&L as a percent of the balance before the trade.
    pnl_pct: float | None
    reason: ExitReason
    balance: float | None
    at: datetime


@dataclass(frozen=True)
class DrawdownWarningEvent:
    """The day's loss has used ``level_pct`` of the daily loss allowance."""

    account_id: str
    level_pct: int
    used_pct: float
    daily_pnl: float
    daily_limit: float
    equity: float
    floor: float
    at: datetime


RiskEvent = Union[HaltEvent, TradeOpenedEvent, TradeClosedEvent, DrawdownWarningEvent]
RiskEventListener = Callable[[RiskEvent], None]
