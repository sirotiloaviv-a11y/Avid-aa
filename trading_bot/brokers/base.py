"""The unified broker interface every adapter implements.

The execution engine talks only to :class:`Broker`. One broker instance may
serve several prop accounts (``account`` is the broker-side account name),
and may be called from several threads at once, one per account.

Positions are **netted per symbol**: at most one position per account and
symbol. That matches futures accounts and one-way mode on crypto venues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from ..risk_manager.events import Direction
from ..risk_manager.position_sizing import AssetClass, InstrumentSpec


class BrokerError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class AccountSnapshot:
    balance: float
    equity: float


@dataclass(frozen=True)
class Position:
    symbol: str
    # Signed: positive long, negative short.
    quantity: float
    avg_price: float

    @property
    def direction(self) -> Direction:
        return Direction.LONG if self.quantity > 0 else Direction.SHORT


@dataclass(frozen=True)
class OrderRequest:
    """A market entry with a protective stop and optional take profit."""

    account: str
    instrument: InstrumentSpec
    direction: Direction
    quantity: Decimal
    stop_price: Decimal
    take_profit: Decimal | None
    # Our id for the trade; sent to the broker where it supports one, so a
    # retried request can never open a second position.
    client_id: str
    reference_price: float

    @property
    def symbol(self) -> str:
        return self.instrument.symbol


@dataclass(frozen=True)
class OrderAck:
    broker_order_id: str
    # Known immediately for simulated fills; None when the venue reports it later.
    fill_price: float | None = None


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    exit_price: float | None
    realized_pnl: float
    closed_at: datetime


@dataclass(frozen=True)
class TradeRef:
    """What the bot recorded about the trade whose close is being looked up."""

    direction: Direction
    quantity: float
    entry_price: float | None


class Broker(ABC):
    name: str = "broker"
    #: None means the broker can trade any asset class (the paper broker).
    asset_class: AssetClass | None = None

    def connect(self) -> None:
        """Authenticate / warm caches. Safe to call again after a failure."""

    def close(self) -> None:
        """Release connections."""

    @abstractmethod
    def account_snapshot(self, account: str) -> AccountSnapshot: ...

    @abstractmethod
    def positions(self, account: str) -> dict[str, Position]:
        """Open positions keyed by *our* instrument symbol (e.g. ``NQ``)."""

    @abstractmethod
    def place_bracket(self, order: OrderRequest) -> OrderAck:
        """Market entry plus exchange-side stop (and target). Never retried blindly."""

    @abstractmethod
    def close_position(self, account: str, symbol: str) -> None:
        """Flatten ``symbol`` at market and cancel its bracket orders."""

    @abstractmethod
    def closed_trade(self, account: str, symbol: str, since: datetime, trade: TradeRef) -> ClosedTrade | None:
        """Result of our position on ``symbol`` (opened at ``since``) once it is closed.

        Only activity at or after ``since`` may count: with a reversal, the
        previous position's exit happens moments before the new entry.
        """


# ------------------------------------------------------------------ prices
def to_tick(price: float | Decimal, tick: Decimal, *, up: bool) -> Decimal:
    """Round a price onto the tick grid, up or down."""
    value = Decimal(str(price))
    steps = (value / tick).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR)
    return steps * tick


def bracket_prices(
    instrument: InstrumentSpec, direction: Direction, stop: float, take_profit: float | None
) -> tuple[Decimal, Decimal | None]:
    """Snap stop and target to the tick grid, always in the conservative direction.

    The stop moves *away* from entry (never tighter than the sized risk, which
    already rounds the stop distance up to whole ticks); the target moves
    *toward* entry, so it is not placed beyond what the strategy asked for.
    """
    long = direction is Direction.LONG
    tick = instrument.tick_size
    stop_px = to_tick(stop, tick, up=not long)
    tp_px = None if take_profit is None else to_tick(take_profit, tick, up=not long)
    return stop_px, tp_px
