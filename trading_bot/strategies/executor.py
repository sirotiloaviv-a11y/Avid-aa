"""Execution engine: strategy signal → risk engine → brokers, per account.

For each signal, every account whose broker trades that asset class is
handled in parallel:

1. **Position check.** Already in that direction: skip. Opposite position:
   close it first (a reversal). FLAT: close and stop.
2. **Risk gate and sizing.** ``RiskEngine.plan_trade`` checks halts, the
   news blackout, stale data and trade count, then sizes the position for
   *this* account's equity and limits. Anything but "approved" means no order.
3. **Order.** Market entry with an exchange-side stop (and target), prices
   snapped to the tick grid.
4. **Journal.** ``record_trade_opened``, which also fires the Telegram alert
   and the dashboard update.

:meth:`reconcile` runs every few seconds. It feeds broker balances to the
risk engine, detects positions that closed (stop, target, manual) and
records their P&L, and flags positions the bot does not know about.

The broker is the source of truth for positions. If an order call fails
ambiguously (timeout), the order may still have filled; reconcile adopts a
matching position that appears shortly afterwards instead of ignoring it.
"""

from __future__ import annotations

import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from typing import Callable, Mapping, Sequence

from ..brokers.base import Broker, BrokerError, OrderRequest, Position, TradeRef, bracket_prices
from ..risk_manager.events import Direction, ExitReason, HaltEvent, HaltKind
from ..risk_manager.position_sizing import INSTRUMENTS, AssetClass, InstrumentSpec
from ..risk_manager.risk_engine import OpenTrade, RiskEngine, RiskManager
from ..utils.logger import get_logger
from ..utils.time_utils import utc_now
from .models import Side, Signal

log = get_logger(__name__)

CLOSE_INFO_GRACE = timedelta(minutes=2)
UNCERTAIN_ORDER_WINDOW = timedelta(minutes=2)
ALERT_AFTER_FAILURES = 3


class ExecutionStatus(str, Enum):
    FILLED = "filled"
    CLOSED = "closed"
    SKIPPED = "skipped"      # nothing to do (already positioned, flat, wrong asset class)
    REJECTED = "rejected"    # the risk engine said no
    FAILED = "failed"        # broker error


@dataclass(frozen=True)
class AccountRoute:
    account_id: str                     # risk-engine account id
    broker: str                         # key into the brokers mapping
    broker_account: str                 # account name at the broker
    asset_classes: frozenset[AssetClass] = field(
        default_factory=lambda: frozenset({AssetClass.FUTURES, AssetClass.CRYPTO}))


@dataclass(frozen=True)
class ExecutionResult:
    account_id: str
    symbol: str
    status: ExecutionStatus
    message: str = ""
    trade_id: str | None = None
    quantity: Decimal | None = None


def risk_amount(spec: InstrumentSpec, entry: float, stop: float, quantity: Decimal) -> float:
    ticks = (Decimal(str(abs(entry - stop))) / spec.tick_size).to_integral_value(ROUND_CEILING)
    return float((ticks * spec.tick_value + spec.fee_per_unit) * quantity)


HALT_EXIT_REASON: dict[str, ExitReason] = {
    HaltKind.DAILY_LOSS: ExitReason.DAILY_HALT,
    HaltKind.MAX_DRAWDOWN: ExitReason.RISK_HALT,
    HaltKind.MANUAL: ExitReason.MANUAL,
}


def _no_alert(_message: str) -> None:
    return None


class ExecutionEngine:
    def __init__(
        self,
        manager: RiskManager,
        routes: Sequence[AccountRoute],
        brokers: Mapping[str, Broker],
        *,
        instruments: Mapping[str, InstrumentSpec] = INSTRUMENTS,
        alert: Callable[[str], None] | None = None,
        max_signal_age: timedelta | None = None,
        clock: Callable[[], datetime] = utc_now,
        max_workers: int = 8,
    ) -> None:
        for route in routes:
            if route.broker not in brokers:
                raise ValueError(f"route {route.account_id} uses unknown broker {route.broker!r}")
            manager[route.account_id]  # KeyError early for a typo'd account
        self.manager = manager
        self.routes = {r.account_id: r for r in routes}
        self.brokers = dict(brokers)
        self.instruments = dict(instruments)
        self._alert: Callable[[str], None] = alert or _no_alert
        self.max_signal_age = max_signal_age
        self._clock = clock
        self._pool = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(routes) or 1)),
                                        thread_name_prefix="exec")
        self._exit_reasons: dict[str, ExitReason] = {}
        self._missing_since: dict[str, datetime] = {}
        self._uncertain: dict[tuple[str, str], tuple[OrderRequest, datetime]] = {}
        self._warned_unmanaged: set[tuple[str, str]] = set()
        self._failures: dict[str, int] = {}
        self._requests: queue.Queue[tuple[str | None, ExitReason]] = queue.Queue()
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------ wiring
    def on_halt(self, event: HaltEvent) -> None:
        """Risk-engine halt listener: queue a flatten for the loop thread.

        Called under the engine's lock, possibly from the dashboard's thread,
        so it must not make broker calls itself.
        """
        if event.should_flatten:
            self.request_flatten(event.account_id, HALT_EXIT_REASON.get(event.kind, ExitReason.OTHER))

    def request_flatten(self, account_id: str | None, reason: ExitReason) -> None:
        """Thread-safe. ``None`` flattens every account."""
        self._requests.put((account_id, reason))

    def process_requests(self) -> None:
        while True:
            try:
                account_id, reason = self._requests.get_nowait()
            except queue.Empty:
                return
            if account_id is None:
                self.flatten_all(reason)
            elif account_id in self.routes:
                self.flatten(account_id, reason)

    def close(self) -> None:
        self._pool.shutdown(wait=True)

    # ----------------------------------------------------------- signals
    def on_signal(self, signal: Signal) -> list[ExecutionResult]:
        spec = self.instruments.get(signal.symbol)
        if spec is None:
            log.error("Signal for unknown instrument %s ignored", signal.symbol)
            return []
        if self.max_signal_age is not None:
            age = self._clock() - signal.time
            if age > self.max_signal_age:
                log.warning("Stale %s signal on %s (%.0fs old) ignored", signal.side.value, signal.symbol,
                            age.total_seconds())
                return []
        routes = [r for r in self.routes.values() if spec.asset_class in r.asset_classes
                  and (self.brokers[r.broker].asset_class in (None, spec.asset_class))]
        if not routes:
            return []
        log.info("Signal %s %s @ %.4f (%s) -> %d account(s)", signal.side.value.upper(), signal.symbol,
                 signal.price, signal.reason, len(routes))
        futures = [self._pool.submit(self._execute, route, spec, signal) for route in routes]
        results = [f.result() for f in futures]
        for result in results:
            log.info("[%s] %s %s: %s", result.account_id, signal.symbol, result.status.value, result.message)
            if result.status is ExecutionStatus.FAILED:
                self._alert(f"⚠️ Order FAILED on <code>{result.account_id}</code> {signal.symbol}: {result.message}")
        return results

    def _execute(self, route: AccountRoute, spec: InstrumentSpec, signal: Signal) -> ExecutionResult:
        try:
            return self._execute_unsafe(route, spec, signal)
        except Exception as exc:  # one account's bug must not stop the others
            log.exception("[%s] execution error", route.account_id)
            return ExecutionResult(route.account_id, signal.symbol, ExecutionStatus.FAILED, f"error: {exc}")

    def _execute_unsafe(self, route: AccountRoute, spec: InstrumentSpec, signal: Signal) -> ExecutionResult:
        engine = self.manager[route.account_id]
        symbol = signal.symbol
        current = self._open_trade(engine, symbol)

        if signal.side is Side.FLAT:
            if current is None:
                return ExecutionResult(route.account_id, symbol, ExecutionStatus.SKIPPED, "already flat")
            closed = self._close_trade(route, current, ExitReason.SIGNAL)
            status = ExecutionStatus.CLOSED if closed else ExecutionStatus.FAILED
            return ExecutionResult(route.account_id, symbol, status,
                                   "position closed" if closed else "close not confirmed yet",
                                   current.trade_id)

        direction = Direction.LONG if signal.side is Side.LONG else Direction.SHORT
        if current is not None:
            if current.direction == direction.value:
                return ExecutionResult(route.account_id, symbol, ExecutionStatus.SKIPPED,
                                       f"already {direction.value}", current.trade_id)
            if not self._close_trade(route, current, ExitReason.SIGNAL):
                return ExecutionResult(route.account_id, symbol, ExecutionStatus.FAILED,
                                       "reversal: previous position not closed yet")

        assert signal.stop is not None  # Signal validates this for LONG/SHORT
        stop, target = bracket_prices(spec, direction, signal.stop, signal.take_profit)
        plan = engine.plan_trade(spec, signal.price, stop)
        if not plan.approved or plan.size is None:
            return ExecutionResult(route.account_id, symbol, ExecutionStatus.REJECTED,
                                   "; ".join(plan.decision.reasons) or "not approved")

        broker = self.brokers[route.broker]
        order = OrderRequest(route.broker_account, spec, direction, plan.size.quantity, stop, target,
                             f"tb{uuid.uuid4().hex[:18]}", signal.price)
        try:
            ack = broker.place_bracket(order)
        except BrokerError as exc:
            if exc.retryable:
                # Timeout / network: the order may have reached the venue.
                with self._state_lock:
                    self._uncertain[(route.account_id, symbol)] = (order, self._clock())
            return ExecutionResult(route.account_id, symbol, ExecutionStatus.FAILED, str(exc))

        entry = ack.fill_price if ack.fill_price is not None else signal.price
        self._record_open(engine, order, entry)
        return ExecutionResult(route.account_id, symbol, ExecutionStatus.FILLED,
                               f"{direction.value} {order.quantity} @ {entry:.4f} stop {stop}",
                               order.client_id, order.quantity)

    def _record_open(self, engine: RiskEngine, order: OrderRequest, entry: float) -> None:
        engine.record_trade_opened(
            order.client_id, order.symbol,
            risk_amount(order.instrument, entry, float(order.stop_price), order.quantity),
            direction=order.direction, entry_price=entry, stop_price=float(order.stop_price),
            take_profit=float(order.take_profit) if order.take_profit is not None else None,
            quantity=order.quantity,
        )

    @staticmethod
    def _open_trade(engine: RiskEngine, symbol: str) -> OpenTrade | None:
        for trade in engine.status().open_trades:
            if trade.symbol == symbol:
                return trade
        return None

    # ----------------------------------------------------------- closing
    def _close_trade(self, route: AccountRoute, trade: OpenTrade, reason: ExitReason) -> bool:
        """Close at the broker, then record it. Returns whether it is closed."""
        broker = self.brokers[route.broker]
        try:
            # It may already be gone (stop or target hit since the last
            # reconcile): then its own exit reason applies, not ours.
            if trade.symbol in broker.positions(route.broker_account):
                with self._state_lock:
                    self._exit_reasons[trade.trade_id] = reason
                broker.close_position(route.broker_account, trade.symbol)
        except BrokerError as exc:
            log.error("[%s] close %s failed: %s", route.account_id, trade.symbol, exc)
            self._alert(f"⚠️ Could not close {trade.symbol} on <code>{route.account_id}</code>: {exc}")
            return False
        self.reconcile_account(route)
        return self._open_trade(self.manager[route.account_id], trade.symbol) is None

    def flatten(self, account_id: str, reason: ExitReason) -> list[ExecutionResult]:
        route = self.routes[account_id]
        engine = self.manager[account_id]
        results: list[ExecutionResult] = []
        for trade in engine.status().open_trades:
            closed = self._close_trade(route, trade, reason)
            results.append(ExecutionResult(account_id, trade.symbol,
                                           ExecutionStatus.CLOSED if closed else ExecutionStatus.FAILED,
                                           f"flatten ({reason.value})", trade.trade_id))
        if results:
            log.warning("[%s] flattened %d position(s): %s", account_id, len(results), reason.value)
        return results

    def flatten_all(self, reason: ExitReason) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for account_id in self.routes:
            results.extend(self.flatten(account_id, reason))
        return results

    def open_position_count(self) -> int:
        return sum(len(self.manager[a].status().open_trades) for a in self.routes)

    # --------------------------------------------------------- reconcile
    def reconcile(self) -> None:
        for route in self.routes.values():
            self.reconcile_account(route)

    def reconcile_account(self, route: AccountRoute) -> None:
        broker = self.brokers[route.broker]
        engine = self.manager[route.account_id]
        try:
            positions = broker.positions(route.broker_account)
            snapshot = broker.account_snapshot(route.broker_account)
        except BrokerError as exc:
            count = self._failures.get(route.account_id, 0) + 1
            self._failures[route.account_id] = count
            log.warning("[%s] reconcile failed (%d in a row): %s", route.account_id, count, exc)
            if count == ALERT_AFTER_FAILURES:
                self._alert(f"⚠️ Broker unreachable for <code>{route.account_id}</code>: {exc}. "
                            "New entries are blocked until data is fresh again.")
            return
        if self._failures.pop(route.account_id, 0) >= ALERT_AFTER_FAILURES:
            self._alert(f"✅ Broker connection restored for <code>{route.account_id}</code>")

        now = self._clock()
        tracked = {t.symbol: t for t in engine.status().open_trades}
        for symbol, trade in tracked.items():
            if symbol not in positions:
                self._record_close(route, engine, trade, snapshot.balance, now)
        for symbol, position in positions.items():
            if symbol not in tracked:
                self._untracked(route, engine, symbol, position, now)
        engine.update_account(snapshot.balance, snapshot.equity, now=now)

    def _record_close(self, route: AccountRoute, engine: RiskEngine, trade: OpenTrade,
                      balance: float, now: datetime) -> None:
        broker = self.brokers[route.broker]
        opened = datetime.fromisoformat(trade.opened_at)
        try:
            ref = TradeRef(Direction(trade.direction or "long"), trade.quantity or 0.0, trade.entry_price)
            closed = broker.closed_trade(route.broker_account, trade.symbol, opened, ref)
        except BrokerError as exc:
            log.warning("[%s] closed-trade lookup for %s failed: %s", route.account_id, trade.symbol, exc)
            closed = None
        with self._state_lock:
            if closed is None:
                first = self._missing_since.setdefault(trade.trade_id, now)
                if now - first < CLOSE_INFO_GRACE:
                    return  # the venue may not have published the fills yet
                self._alert(f"⚠️ {trade.symbol} on <code>{route.account_id}</code> is flat at the broker "
                            "but its P&amp;L is unavailable; recorded as 0. Check the broker statement.")
            self._missing_since.pop(trade.trade_id, None)
            reason = self._exit_reasons.pop(trade.trade_id, None)
        exit_price = closed.exit_price if closed else None
        engine.record_trade_closed(
            trade.trade_id, closed.realized_pnl if closed else 0.0,
            exit_price=exit_price, reason=reason or self._infer_reason(trade, exit_price),
            balance=balance, now=now,
        )

    @staticmethod
    def _infer_reason(trade: OpenTrade, exit_price: float | None) -> ExitReason:
        if exit_price is None or trade.stop_price is None:
            return ExitReason.OTHER
        to_stop = abs(exit_price - trade.stop_price)
        if trade.take_profit is not None and abs(exit_price - trade.take_profit) < to_stop:
            return ExitReason.TAKE_PROFIT
        return ExitReason.STOP_LOSS

    def _untracked(self, route: AccountRoute, engine: RiskEngine, symbol: str,
                   position: Position, now: datetime) -> None:
        key = (route.account_id, symbol)
        with self._state_lock:
            pending = self._uncertain.pop(key, None)
        if pending is not None:
            order, sent_at = pending
            if now - sent_at <= UNCERTAIN_ORDER_WINDOW and position.direction is order.direction:
                log.warning("[%s] adopting %s position from an order that timed out", route.account_id, symbol)
                self._record_open(engine, order, position.avg_price or order.reference_price)
                self._alert(f"ℹ️ Order on <code>{route.account_id}</code> {symbol} timed out but filled; "
                            "now tracked with its stop.")
                return
        if key not in self._warned_unmanaged:
            self._warned_unmanaged.add(key)
            log.error("[%s] untracked %s position at the broker: %s", route.account_id, symbol, position)
            self._alert(f"⚠️ Untracked {symbol} position on <code>{route.account_id}</code> "
                        f"(qty {position.quantity:g} @ {position.avg_price:g}). The bot will not manage it.")
