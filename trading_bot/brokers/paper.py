"""Paper broker: simulated fills, stops and targets, no money at risk.

* Market orders fill at the last price, moved ``slippage_ticks`` against you.
* Stops and targets are checked on every bar's high/low. If a bar touches
  both, the **stop** is assumed to fill first (the pessimistic reading of an
  OHLC bar). A bar that opens through the stop fills at the open, not the stop.
* ``fee_per_unit`` from the instrument spec is charged on close.

State is saved in the bot's SQLite store, so paper balances and positions
survive restarts just like a real account.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

from ..risk_manager.events import Direction
from ..risk_manager.position_sizing import INSTRUMENTS, InstrumentSpec
from ..strategies.models import Candle
from ..utils.logger import get_logger
from ..utils.state_store import StateStore, StateStoreError
from ..utils.time_utils import utc_now
from .base import (
    AccountSnapshot,
    Broker,
    BrokerError,
    ClosedTrade,
    OrderAck,
    OrderRequest,
    Position,
    TradeRef,
)

log = get_logger(__name__)

STATE_KEY = "paper_broker"


@dataclass
class _PaperPosition:
    direction: Direction
    quantity: float
    entry: float
    stop: float | None
    take_profit: float | None
    opened_at: str


@dataclass
class _PaperAccount:
    balance: float
    positions: dict[str, _PaperPosition] = field(default_factory=lambda: dict[str, _PaperPosition]())
    closed: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())


class PaperBroker(Broker):
    name = "paper"
    asset_class = None

    def __init__(
        self,
        accounts: Mapping[str, float],
        *,
        instruments: Mapping[str, InstrumentSpec] = INSTRUMENTS,
        slippage_ticks: int = 1,
        store: StateStore | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.instruments = dict(instruments)
        self.slippage_ticks = slippage_ticks
        self.store = store
        self._clock = clock
        self._lock = threading.RLock()
        self._prices: dict[str, float] = {}
        self._accounts = {name: _PaperAccount(balance) for name, balance in accounts.items()}
        self._order_seq = 0
        self._load()

    # ------------------------------------------------------------ storage
    def _load(self) -> None:
        if self.store is None:
            return
        raw = self.store.get_value(STATE_KEY)
        if not raw:
            return
        data: dict[str, Any] = json.loads(raw)
        for name, acc in dict(data.get("accounts", {})).items():
            if name not in self._accounts:
                continue
            positions = {
                sym: _PaperPosition(Direction(p["direction"]), p["quantity"], p["entry"], p["stop"],
                                    p["take_profit"], p["opened_at"])
                for sym, p in dict(acc.get("positions", {})).items()
            }
            self._accounts[name] = _PaperAccount(float(acc["balance"]), positions, list(acc.get("closed", [])))
        self._prices.update({k: float(v) for k, v in dict(data.get("prices", {})).items()})

    def _save(self) -> None:
        if self.store is None:
            return
        data = {
            "accounts": {
                name: {
                    "balance": acc.balance,
                    "positions": {s: {**p.__dict__, "direction": p.direction.value}
                                  for s, p in acc.positions.items()},
                    "closed": acc.closed[-200:],
                }
                for name, acc in self._accounts.items()
            },
            "prices": self._prices,
        }
        try:
            self.store.set_value(STATE_KEY, json.dumps(data))
        except StateStoreError as exc:
            log.error("Paper broker state not saved: %s", exc)

    # ------------------------------------------------------------- helpers
    def _account(self, account: str) -> _PaperAccount:
        try:
            return self._accounts[account]
        except KeyError:
            raise BrokerError(f"paper broker has no account {account!r}") from None

    def _instrument(self, symbol: str) -> InstrumentSpec:
        try:
            return self.instruments[symbol]
        except KeyError:
            raise BrokerError(f"paper broker has no instrument {symbol!r}") from None

    def _slip(self, symbol: str, price: float, *, buying: bool) -> float:
        tick = float(self._instrument(symbol).tick_size)
        return price + tick * self.slippage_ticks * (1 if buying else -1)

    def _pnl(self, symbol: str, pos: _PaperPosition, exit_price: float) -> float:
        spec = self._instrument(symbol)
        point_value = float(spec.tick_value / spec.tick_size)
        sign = 1 if pos.direction is Direction.LONG else -1
        return (exit_price - pos.entry) * sign * pos.quantity * point_value - float(spec.fee_per_unit) * pos.quantity

    def _close(self, account: _PaperAccount, symbol: str, exit_price: float, when: datetime) -> None:
        pos = account.positions.pop(symbol)
        pnl = self._pnl(symbol, pos, exit_price)
        account.balance += pnl
        account.closed.append({"symbol": symbol, "exit_price": exit_price, "pnl": pnl,
                               "closed_at": when.isoformat()})
        log.info("[paper] closed %s %s x%s @ %.4f pnl=%.2f", pos.direction.value, symbol,
                 pos.quantity, exit_price, pnl)

    # -------------------------------------------------------- market data
    def on_candle(self, candle: Candle) -> None:
        """Advance the simulation: trigger stops/targets inside this bar."""
        with self._lock:
            for account in self._accounts.values():
                pos = account.positions.get(candle.symbol)
                if pos is None:
                    continue
                exit_price = self._trigger(candle, pos)
                if exit_price is not None:
                    # Stamped on the wall clock, like a real venue's fill time.
                    self._close(account, candle.symbol, exit_price, self._clock())
            self._prices[candle.symbol] = candle.close
            self._save()

    def _trigger(self, candle: Candle, pos: _PaperPosition) -> float | None:
        long = pos.direction is Direction.LONG
        if pos.stop is not None:
            if long and candle.low <= pos.stop:
                fill = min(pos.stop, candle.open)
                return self._slip(candle.symbol, fill, buying=False)
            if not long and candle.high >= pos.stop:
                fill = max(pos.stop, candle.open)
                return self._slip(candle.symbol, fill, buying=True)
        if pos.take_profit is not None:
            if long and candle.high >= pos.take_profit:
                return max(pos.take_profit, candle.open)
            if not long and candle.low <= pos.take_profit:
                return min(pos.take_profit, candle.open)
        return None

    def set_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self._prices[symbol] = price

    # ---------------------------------------------------------- interface
    def account_snapshot(self, account: str) -> AccountSnapshot:
        with self._lock:
            acc = self._account(account)
            unrealized = sum(
                self._pnl(sym, pos, self._prices.get(sym, pos.entry)) + float(self._instrument(sym).fee_per_unit) * pos.quantity
                for sym, pos in acc.positions.items()
            )
            return AccountSnapshot(balance=acc.balance, equity=acc.balance + unrealized)

    def positions(self, account: str) -> dict[str, Position]:
        with self._lock:
            acc = self._account(account)
            return {
                sym: Position(sym, pos.quantity * (1 if pos.direction is Direction.LONG else -1), pos.entry)
                for sym, pos in acc.positions.items()
            }

    def place_bracket(self, order: OrderRequest) -> OrderAck:
        with self._lock:
            acc = self._account(order.account)
            symbol = order.symbol
            self._instrument(symbol)
            if symbol in acc.positions:
                raise BrokerError(f"{order.account} already has a {symbol} position")
            last = self._prices.get(symbol)
            if last is None:
                raise BrokerError(f"no price for {symbol} yet")
            buying = order.direction is Direction.LONG
            fill = self._slip(symbol, last, buying=buying)
            acc.positions[symbol] = _PaperPosition(
                order.direction, float(order.quantity), fill, float(order.stop_price),
                float(order.take_profit) if order.take_profit is not None else None,
                self._clock().isoformat(),
            )
            self._order_seq += 1
            self._save()
            log.info("[paper] %s %s %s x%s @ %.4f (stop %s, tp %s)", order.account, order.direction.value,
                     symbol, order.quantity, fill, order.stop_price, order.take_profit)
            return OrderAck(f"paper-{self._order_seq}-{order.client_id}", fill)

    def close_position(self, account: str, symbol: str) -> None:
        with self._lock:
            acc = self._account(account)
            pos = acc.positions.get(symbol)
            if pos is None:
                return
            last = self._prices.get(symbol, pos.entry)
            exit_price = self._slip(symbol, last, buying=pos.direction is Direction.SHORT)
            self._close(acc, symbol, exit_price, self._clock())
            self._save()

    def closed_trade(self, account: str, symbol: str, since: datetime, trade: TradeRef) -> ClosedTrade | None:
        with self._lock:
            for entry in reversed(self._account(account).closed):
                closed_at = datetime.fromisoformat(entry["closed_at"])
                if entry["symbol"] == symbol and closed_at >= since:
                    return ClosedTrade(symbol, float(entry["exit_price"]), float(entry["pnl"]), closed_at)
        return None
