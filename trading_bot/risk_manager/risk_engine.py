"""Fail-safe risk engine for prop firm accounts.

One :class:`RiskEngine` guards one account. It is fed account snapshots
(balance + equity) and answers one question before every entry: *may this
trade be opened, and at what size?*

Design rules, in priority order:

1. **Fail closed.** Missing data, stale equity, an unreadable state file, a
   failed state write, an unavailable news calendar or an internal error all
   deny new trades. The engine never answers "yes" by default.
2. **Halts are sticky and persisted.** A daily-loss halt lasts until the prop
   firm's daily reset; a max-drawdown breach lasts until a human clears it.
   Both are written to SQLite before anything else happens, so a crash-loop
   restart cannot trade through them.
3. **Size to the remaining room, not just the risk %.** A trade is sized to
   the smaller of the per-trade risk budget and the distance to the nearest
   loss floor (minus the risk already committed to open trades), so no single
   stop-out can breach a limit.

The engine does not place or close orders. On a breach it reports
``should_flatten`` and calls the registered halt callbacks; the execution
layer is responsible for closing positions.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, cast

from ..config import (
    AccountConfig,
    DailyLossBasis,
    DrawdownMode,
    RiskLimits,
    SessionConfig,
    Settings,
)
from ..utils.logger import get_logger
from ..utils.state_store import StateStore, StateStoreError
from ..utils.time_utils import ensure_utc, next_reset, trading_day, utc_now
from .events import (
    Direction,
    DrawdownWarningEvent,
    ExitReason,
    HaltEvent,
    HaltKind,
    RiskEvent,
    RiskEventListener,
    TradeClosedEvent,
    TradeOpenedEvent,
)
from .news_guard import NewsGuard
from .position_sizing import (
    InstrumentSpec,
    PositionSize,
    PositionSizingError,
    calculate_position_size,
)

log = get_logger(__name__)

STATE_VERSION = 1


@dataclass
class OpenTrade:
    trade_id: str
    symbol: str
    risk: float
    opened_at: str
    direction: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    take_profit: float | None = None
    quantity: float | None = None


@dataclass
class AccountState:
    """Everything that must survive a restart. Serialized as JSON."""

    account_id: str
    initial_balance: float
    version: int = STATE_VERSION
    trading_day: str | None = None
    day_start_balance: float | None = None
    day_start_equity: float | None = None
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    closed_today: int = 0
    # Daily-loss warning levels (percent of the allowance) already announced.
    daily_warnings_sent: list[int] = field(default_factory=lambda: list[int]())
    balance: float | None = None
    equity: float | None = None
    last_update: str | None = None
    high_water_mark: float = 0.0
    daily_halted: bool = False
    daily_halt_reason: str | None = None
    max_dd_breached: bool = False
    max_dd_reason: str | None = None
    manual_halt: bool = False
    manual_halt_reason: str | None = None
    open_trades: dict[str, OpenTrade] = field(default_factory=lambda: dict[str, OpenTrade]())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AccountState:
        known = {f for f in cls.__dataclass_fields__}
        values = {k: v for k, v in data.items() if k in known}
        trades = cast("dict[str, dict[str, Any]]", data.get("open_trades") or {})
        values["open_trades"] = {tid: OpenTrade(**trade) for tid, trade in trades.items()}
        return cls(**values)


@dataclass(frozen=True)
class RiskStatus:
    account_id: str
    trading_day: date | None
    balance: float | None
    equity: float | None
    last_update: datetime | None
    day_start_reference: float | None
    daily_pnl: float | None
    daily_loss_floor: float | None
    daily_room: float | None
    drawdown_floor: float
    drawdown_room: float | None
    high_water_mark: float
    open_risk: float
    trades_today: int
    realized_pnl_today: float
    wins_today: int
    losses_today: int
    closed_today: int
    # Share of today's loss allowance used, 0-100+.
    daily_loss_used_pct: float | None
    open_trades: tuple[OpenTrade, ...]
    halted: bool
    halt_reasons: tuple[str, ...]
    should_flatten: bool
    halted_until: datetime | None


@dataclass(frozen=True)
class TradeDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class TradePlan:
    decision: TradeDecision
    size: PositionSize | None = None

    @property
    def approved(self) -> bool:
        return self.decision.allowed and self.size is not None and self.size.is_tradeable


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name}={value!r} is not a finite number")
    return number


class RiskEngine:
    def __init__(
        self,
        account: AccountConfig,
        limits: RiskLimits,
        session: SessionConfig,
        store: StateStore,
        *,
        news_guard: NewsGuard | None = None,
        kill_switch_path: Path | None = None,
        room_usage_fraction: float = 0.8,
        daily_warning_levels: tuple[int, ...] = (50, 80),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not 0 < room_usage_fraction <= 1:
            raise ValueError("room_usage_fraction must be in (0, 1]")
        self.account = account
        self.limits = limits
        self.session = session
        self.store = store
        self.news_guard = news_guard
        self.kill_switch_path = kill_switch_path
        self.room_usage_fraction = room_usage_fraction
        self.daily_warning_levels = tuple(sorted(lvl for lvl in daily_warning_levels if 0 < lvl < 100))
        self._clock = clock
        self._lock = threading.RLock()
        self._halt_callbacks: list[Callable[[HaltEvent], None]] = []
        self._listeners: list[RiskEventListener] = []
        self._persist_failed = False
        # Raises StateCorruptError / StateStoreError: refusing to start beats
        # starting with a forgotten daily loss.
        self.state = self._load_state()

    # ------------------------------------------------------------ state io
    def _load_state(self) -> AccountState:
        raw = self.store.load_account(self.account.account_id)
        if raw is None:
            log.info("[%s] No saved state; starting fresh", self.account.account_id)
            state = AccountState(
                account_id=self.account.account_id,
                initial_balance=self.account.initial_balance,
                high_water_mark=self.account.initial_balance,
            )
            self.store.save_account(state.account_id, state.to_dict())
            return state
        state = AccountState.from_dict(raw)
        if state.initial_balance != self.account.initial_balance:
            log.warning(
                "[%s] Initial balance changed %.2f -> %.2f (config wins)",
                state.account_id, state.initial_balance, self.account.initial_balance,
            )
            state.initial_balance = self.account.initial_balance
            state.high_water_mark = max(state.high_water_mark, state.initial_balance)
        log.info(
            "[%s] Restored state: day=%s realized=%.2f trades=%d halted=%s",
            state.account_id, state.trading_day, state.realized_pnl_today,
            state.trades_today, self._halt_reasons(state) or "no",
        )
        return state

    def _persist(self) -> None:
        try:
            self.store.save_account(self.state.account_id, self.state.to_dict())
        except StateStoreError as exc:
            if not self._persist_failed:
                log.critical("[%s] STATE NOT SAVED, blocking new trades: %s",
                             self.state.account_id, exc)
            self._persist_failed = True
            return
        if self._persist_failed:
            log.warning("[%s] State saving recovered", self.state.account_id)
        self._persist_failed = False

    # ----------------------------------------------------------- callbacks
    def on_halt(self, callback: Callable[[HaltEvent], None]) -> None:
        """Register a callback fired once per new halt (e.g. flatten positions)."""
        self._halt_callbacks.append(callback)

    def subscribe(self, listener: RiskEventListener) -> None:
        """Receive every risk event: trades, drawdown warnings and halts."""
        self._listeners.append(listener)

    def _publish(self, event: RiskEvent) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                log.exception("[%s] Risk event listener %r failed", self.account.account_id, listener)

    def _emit_halt(self, kind: str, reason: str, now: datetime) -> None:
        event = HaltEvent(self.state.account_id, kind, reason, now, should_flatten=True)
        log.critical("[%s] TRADING HALTED (%s): %s", event.account_id, kind, reason)
        self.store.append_event(event.account_id, f"halt:{kind}", reason, now)
        for callback in self._halt_callbacks:
            try:
                callback(event)
            except Exception:
                log.exception("[%s] Halt callback %r failed", event.account_id, callback)
        self._publish(event)

    # --------------------------------------------------------------- limits
    def _day_reference(self) -> float | None:
        s = self.state
        if s.day_start_balance is None or s.day_start_equity is None:
            return None
        # FTMO-style: the higher of balance and equity at the start of the day.
        return max(s.day_start_balance, s.day_start_equity)

    def daily_loss_floor(self) -> float | None:
        reference = self._day_reference()
        if reference is None:
            return None
        base = (
            self.state.initial_balance
            if self.limits.daily_loss_basis is DailyLossBasis.INITIAL
            else reference
        )
        return reference - base * self.limits.daily_loss_limit_pct / 100

    def drawdown_floor(self) -> float:
        initial = self.state.initial_balance
        allowance = initial * self.limits.max_drawdown_pct / 100
        if self.limits.max_drawdown_mode is DrawdownMode.STATIC:
            return initial - allowance
        floor = self.state.high_water_mark - allowance
        if self.limits.drawdown_lock_at_initial:
            floor = min(floor, initial)
        return floor

    # ------------------------------------------------------------- updates
    def update_account(self, balance: float, equity: float, *, now: datetime | None = None) -> RiskStatus:
        """Feed a fresh account snapshot. Call this on every broker update."""
        balance = _finite("balance", balance)
        equity = _finite("equity", equity)
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            self._roll_day_if_needed(now, balance, equity)
            s = self.state
            s.balance, s.equity, s.last_update = balance, equity, now.isoformat()
            if self.limits.max_drawdown_mode is DrawdownMode.TRAILING_INTRADAY:
                s.high_water_mark = max(s.high_water_mark, equity)
            self._evaluate_limits(now)
            self._persist()
            return self._status(now)

    def _roll_day_if_needed(self, now: datetime, balance: float, equity: float) -> None:
        s = self.state
        today = trading_day(now, self.session.reset_tz, self.session.reset_time)
        if s.trading_day == today.isoformat():
            return
        if s.trading_day is not None:
            log.info(
                "[%s] Trading day %s closed: realized=%.2f trades=%d last_balance=%s",
                s.account_id, s.trading_day, s.realized_pnl_today, s.trades_today, s.balance,
            )
            if self.limits.max_drawdown_mode is DrawdownMode.TRAILING_EOD and s.balance is not None:
                s.high_water_mark = max(s.high_water_mark, s.balance)
            if s.daily_halted:
                log.info("[%s] Daily halt cleared by reset", s.account_id)
                self.store.append_event(s.account_id, "daily_reset", "daily halt cleared", now)
        s.trading_day = today.isoformat()
        s.day_start_balance = balance
        s.day_start_equity = equity
        s.realized_pnl_today = 0.0
        s.trades_today = 0
        s.wins_today = s.losses_today = s.closed_today = 0
        s.daily_warnings_sent = []
        s.daily_halted = False
        s.daily_halt_reason = None
        log.info(
            "[%s] Trading day %s started: balance=%.2f equity=%.2f daily_floor=%.2f dd_floor=%.2f",
            s.account_id, s.trading_day, balance, equity,
            self.daily_loss_floor() or 0.0, self.drawdown_floor(),
        )

    def _evaluate_limits(self, now: datetime) -> None:
        s = self.state
        if s.equity is None:
            return
        daily_floor = self.daily_loss_floor()
        used = self._daily_loss_used_pct()
        if used is not None and daily_floor is not None and not s.daily_halted:
            new_levels = [lvl for lvl in self.daily_warning_levels
                          if used >= lvl and lvl not in s.daily_warnings_sent]
            if new_levels:
                s.daily_warnings_sent = sorted({*s.daily_warnings_sent, *new_levels})
            # A single drop straight through the floor gets the halt alert only.
            if new_levels and s.equity > daily_floor:
                self._persist()
                reference = self._day_reference() or 0.0
                level = max(new_levels)
                log.warning("[%s] Daily loss at %.0f%% of allowance (warning level %d%%)",
                            s.account_id, used, level)
                self._publish(DrawdownWarningEvent(
                    account_id=s.account_id, level_pct=level, used_pct=used,
                    daily_pnl=s.equity - reference, daily_limit=reference - daily_floor,
                    equity=s.equity, floor=daily_floor, at=now,
                ))
        if not s.daily_halted and daily_floor is not None and s.equity <= daily_floor:
            reference = self._day_reference() or 0.0
            s.daily_halted = True
            s.daily_halt_reason = (
                f"daily loss limit hit: equity {s.equity:.2f} <= floor {daily_floor:.2f} "
                f"(day P&L {s.equity - reference:.2f})"
            )
            self._persist()
            self._emit_halt(HaltKind.DAILY_LOSS, s.daily_halt_reason, now)

        dd_floor = self.drawdown_floor()
        if not s.max_dd_breached and s.equity <= dd_floor:
            s.max_dd_breached = True
            s.max_dd_reason = (
                f"max drawdown hit: equity {s.equity:.2f} <= floor {dd_floor:.2f} "
                f"(high-water mark {s.high_water_mark:.2f})"
            )
            self._persist()
            self._emit_halt(HaltKind.MAX_DRAWDOWN, s.max_dd_reason, now)

    # ------------------------------------------------------------- trades
    def _daily_loss_used_pct(self) -> float | None:
        reference, floor, equity = self._day_reference(), self.daily_loss_floor(), self.state.equity
        if reference is None or floor is None or equity is None or reference <= floor:
            return None
        return max(0.0, (reference - equity) / (reference - floor) * 100)

    def record_trade_opened(
        self,
        trade_id: str,
        symbol: str,
        risk: float,
        *,
        direction: Direction | None = None,
        entry_price: float | None = None,
        stop_price: float | None = None,
        take_profit: float | None = None,
        quantity: float | Decimal | None = None,
        now: datetime | None = None,
    ) -> None:
        """Register a filled entry. ``risk`` is the loss if its stop is hit."""
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            s = self.state
            if trade_id in s.open_trades:
                log.warning("[%s] Trade %s already recorded as open", s.account_id, trade_id)
                return
            risk = max(0.0, _finite("risk", risk))
            s.open_trades[trade_id] = OpenTrade(
                trade_id, symbol, risk, now.isoformat(),
                direction=direction.value if direction else None,
                entry_price=entry_price, stop_price=stop_price, take_profit=take_profit,
                quantity=float(quantity) if quantity is not None else None,
            )
            s.trades_today += 1
            self._persist()
            log.info("[%s] Opened %s %s risk=%.2f (trade %d/%d today)",
                     s.account_id, trade_id, symbol, risk,
                     s.trades_today, self.limits.max_trades_per_day)
            balance = s.balance
        self._publish(TradeOpenedEvent(
            account_id=self.account.account_id, trade_id=trade_id, symbol=symbol,
            direction=direction, entry_price=entry_price, stop_price=stop_price,
            take_profit=take_profit,
            quantity=float(quantity) if quantity is not None else None,
            risk_amount=risk,
            risk_pct=risk / balance * 100 if balance else None,
            balance=balance, at=now,
        ))

    def record_trade_closed(
        self,
        trade_id: str,
        realized_pnl: float,
        *,
        exit_price: float | None = None,
        reason: ExitReason = ExitReason.OTHER,
        balance: float | None = None,
        now: datetime | None = None,
    ) -> None:
        """Register a closed position. ``balance`` is the broker's balance after it."""
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            s = self.state
            pnl = _finite("realized_pnl", realized_pnl)
            trade = s.open_trades.pop(trade_id, None)
            if trade is None:
                log.warning("[%s] Closed unknown trade %s", s.account_id, trade_id)
            s.realized_pnl_today += pnl
            s.closed_today += 1
            if pnl > 0:
                s.wins_today += 1
            elif pnl < 0:
                s.losses_today += 1
            self._persist()
            log.info("[%s] Closed %s pnl=%.2f reason=%s realized_today=%.2f",
                     s.account_id, trade_id, pnl, reason.value, s.realized_pnl_today)
            new_balance = balance if balance is not None else s.balance
            before = (balance - pnl) if balance is not None else s.balance
        self._publish(TradeClosedEvent(
            account_id=self.account.account_id, trade_id=trade_id,
            symbol=trade.symbol if trade else None,
            direction=Direction(trade.direction) if trade and trade.direction else None,
            entry_price=trade.entry_price if trade else None,
            exit_price=exit_price, realized_pnl=pnl,
            pnl_pct=pnl / before * 100 if before else None,
            reason=reason, balance=new_balance, at=now,
        ))

    # -------------------------------------------------------- manual halts
    def halt(self, reason: str, *, now: datetime | None = None) -> None:
        """Operator kill switch for this account; persists until resumed."""
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            self.state.manual_halt = True
            self.state.manual_halt_reason = reason
            self._persist()
            self._emit_halt(HaltKind.MANUAL, reason, now)

    def resume_manual_halt(self) -> None:
        with self._lock:
            self.state.manual_halt = False
            self.state.manual_halt_reason = None
            self._persist()
            self.store.append_event(self.state.account_id, "resume", "manual halt cleared")
            log.warning("[%s] Manual halt cleared by operator", self.state.account_id)

    def clear_max_drawdown_breach(self, confirm_account_id: str) -> None:
        """Only after the prop firm has reset or replaced the account."""
        with self._lock:
            if confirm_account_id != self.state.account_id:
                raise ValueError("confirmation does not match the account id")
            self.state.max_dd_breached = False
            self.state.max_dd_reason = None
            self.state.high_water_mark = max(self.state.initial_balance, self.state.equity or 0.0)
            self._persist()
            self.store.append_event(self.state.account_id, "reset", "max drawdown breach cleared")
            log.warning("[%s] Max drawdown breach cleared by operator", self.state.account_id)

    # ------------------------------------------------------------- checks
    def _halt_reasons(self, state: AccountState) -> list[str]:
        reasons: list[str] = []
        if state.max_dd_breached:
            reasons.append(state.max_dd_reason or "max drawdown breached")
        if state.daily_halted:
            reasons.append(state.daily_halt_reason or "daily loss limit hit")
        if state.manual_halt:
            reasons.append(f"manual halt: {state.manual_halt_reason or 'no reason given'}")
        return reasons

    def check_new_trade(self, *, now: datetime | None = None) -> TradeDecision:
        """May a new position be opened right now? Never raises."""
        try:
            now = ensure_utc(now) if now is not None else self._clock()
            with self._lock:
                return TradeDecision(not (reasons := self._blocking_reasons(now)), tuple(reasons))
        except Exception as exc:  # fail closed on any bug
            log.exception("[%s] Risk check failed; denying trade", self.account.account_id)
            return TradeDecision(False, (f"risk engine error: {exc}",))

    def _blocking_reasons(self, now: datetime) -> list[str]:
        s = self.state
        reasons = self._halt_reasons(s)
        if self.kill_switch_path is not None and self.kill_switch_path.exists():
            reasons.append(f"kill switch file present: {self.kill_switch_path}")
        if self._persist_failed:
            reasons.append("state could not be saved to disk")
        if s.equity is None or s.last_update is None:
            reasons.append("no account snapshot received yet")
        else:
            age = (now - datetime.fromisoformat(s.last_update)).total_seconds()
            if age > self.limits.equity_stale_seconds:
                reasons.append(f"account snapshot is stale ({age:.0f}s old)")
            today = trading_day(now, self.session.reset_tz, self.session.reset_time)
            if s.trading_day != today.isoformat():
                reasons.append("new trading day started; awaiting first snapshot")
        if s.trades_today >= self.limits.max_trades_per_day:
            reasons.append(f"max trades per day reached ({s.trades_today})")
        if self.news_guard is not None:
            news = self.news_guard.check(now)
            if not news.allowed:
                reasons.append(news.reason or "news blackout")
        return reasons

    def risk_budget(self) -> float:
        """Money that one new trade may lose, after all limits and open risk."""
        with self._lock:
            s = self.state
            if s.equity is None:
                return 0.0
            per_trade = s.equity * self.limits.risk_per_trade_pct / 100
            open_risk = sum(t.risk for t in s.open_trades.values())
            floors = [self.drawdown_floor()]
            daily_floor = self.daily_loss_floor()
            if daily_floor is not None:
                floors.append(daily_floor)
            room = s.equity - max(floors) - open_risk
            # Keep a cushion for slippage: a stop-out may fill worse than the stop.
            return max(0.0, min(per_trade, room * self.room_usage_fraction))

    def plan_trade(
        self,
        instrument: InstrumentSpec,
        entry_price: float | Decimal,
        stop_price: float | Decimal,
        *,
        now: datetime | None = None,
    ) -> TradePlan:
        """Pre-trade gate plus sizing. Only act on ``plan.approved``. Never raises."""
        decision = self.check_new_trade(now=now)
        if not decision.allowed:
            log.info("[%s] %s entry denied: %s", self.account.account_id,
                     instrument.symbol, "; ".join(decision.reasons))
            return TradePlan(decision)
        try:
            budget = self.risk_budget()
            size = calculate_position_size(instrument, entry_price, stop_price, Decimal(f"{budget:.2f}"))
        except PositionSizingError as exc:
            return TradePlan(TradeDecision(False, (f"invalid trade: {exc}",)))
        except Exception as exc:
            log.exception("[%s] Position sizing failed; denying trade", self.account.account_id)
            return TradePlan(TradeDecision(False, (f"risk engine error: {exc}",)))
        if not size.is_tradeable:
            return TradePlan(TradeDecision(False, (size.rejected_reason or "size is zero",)), size)
        log.info("[%s] %s approved: qty=%s stop_ticks=%d risk=%.2f budget=%.2f",
                 self.account.account_id, instrument.symbol, size.quantity,
                 size.stop_ticks, size.total_risk, size.risk_budget)
        return TradePlan(decision, size)

    # ------------------------------------------------------------- status
    def status(self, *, now: datetime | None = None) -> RiskStatus:
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            return self._status(now)

    def _status(self, now: datetime) -> RiskStatus:
        s = self.state
        reference = self._day_reference()
        daily_floor = self.daily_loss_floor()
        dd_floor = self.drawdown_floor()
        reasons = self._halt_reasons(s)
        # Max-drawdown and manual halts have no end time: an operator clears them.
        halted_until: datetime | None = None
        if s.daily_halted and not (s.max_dd_breached or s.manual_halt):
            halted_until = next_reset(now, self.session.reset_tz, self.session.reset_time)
        return RiskStatus(
            account_id=s.account_id,
            trading_day=date.fromisoformat(s.trading_day) if s.trading_day else None,
            balance=s.balance,
            equity=s.equity,
            last_update=datetime.fromisoformat(s.last_update) if s.last_update else None,
            day_start_reference=reference,
            daily_pnl=None if reference is None or s.equity is None else s.equity - reference,
            daily_loss_floor=daily_floor,
            daily_room=None if daily_floor is None or s.equity is None else s.equity - daily_floor,
            drawdown_floor=dd_floor,
            drawdown_room=None if s.equity is None else s.equity - dd_floor,
            high_water_mark=s.high_water_mark,
            open_risk=sum(t.risk for t in s.open_trades.values()),
            trades_today=s.trades_today,
            realized_pnl_today=s.realized_pnl_today,
            wins_today=s.wins_today,
            losses_today=s.losses_today,
            closed_today=s.closed_today,
            daily_loss_used_pct=self._daily_loss_used_pct(),
            open_trades=tuple(s.open_trades.values()),
            halted=bool(reasons),
            halt_reasons=tuple(reasons),
            should_flatten=bool(reasons),
            halted_until=halted_until,
        )


class RiskManager:
    """The risk engines for every configured account, sharing one store."""

    def __init__(self, engines: Mapping[str, RiskEngine]) -> None:
        self._engines = dict(engines)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        store: StateStore,
        *,
        news_guard: NewsGuard | None = None,
        kill_switch_path: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> RiskManager:
        return cls({
            account.account_id: RiskEngine(
                account, settings.risk, settings.session, store,
                news_guard=news_guard,
                kill_switch_path=kill_switch_path,
                room_usage_fraction=settings.risk.room_usage_fraction,
                daily_warning_levels=settings.risk.daily_warning_levels,
                clock=clock,
            )
            for account in settings.accounts
        })

    def __getitem__(self, account_id: str) -> RiskEngine:
        return self._engines[account_id]

    def __iter__(self) -> Iterator[RiskEngine]:
        return iter(self._engines.values())

    def __len__(self) -> int:
        return len(self._engines)

    def on_halt(self, callback: Callable[[HaltEvent], None]) -> None:
        for engine in self._engines.values():
            engine.on_halt(callback)

    def subscribe(self, listener: RiskEventListener) -> None:
        for engine in self._engines.values():
            engine.subscribe(listener)

    def statuses(self, *, now: datetime | None = None) -> list[RiskStatus]:
        return [engine.status(now=now) for engine in self._engines.values()]
