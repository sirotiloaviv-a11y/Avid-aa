"""Avid Desk — a multi-account trading console (MVP).

A single-file Streamlit application that puts three things on one screen:

  1. A live TradingView-style candlestick chart (Lightweight Charts, injected
     as an HTML/JS component so no extra Python wrapper is required).
  2. A Buy / Sell execution panel that fills on a master account and copies
     the order out to sub-accounts spread across several email sessions.
  3. A sidebar portfolio and risk monitor: per-account equity, open
     positions, live max-drawdown and a kill switch.

Everything behind the UI is mocked: prices come from a simulated websocket
feed (a background thread with deliberate disconnects), and broker responses
come from a simulated router with latency, rejects and retries. That is on
purpose — the point of the MVP is to exercise the UI and the routing logic
before any real broker credentials exist. Swapping the mocks for a real feed
and a real broker means replacing two classes, `MarketDataFeed` and
`OrderRouter`, and nothing else.

Run it with:

    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

APP_TITLE = "Avid Desk"
APP_CAPTION = "Multi-account execution console — simulated feed, simulated brokers"

TICK_INTERVAL = 0.25          # seconds between simulated ticks
TICK_HISTORY = 20_000         # raw ticks retained per symbol
SEED_TICKS = 7_200            # ticks of history generated at boot (~30 min)
STALE_AFTER = 5.0             # seconds without a tick before the feed reads stale

TIMEFRAMES: Dict[str, int] = {"1s": 1, "5s": 5, "15s": 15, "1m": 60, "5m": 300}
DEFAULT_TIMEFRAME = "5s"

CHART_CDN = (
    "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/"
    "lightweight-charts.standalone.production.js"
)


@dataclass(frozen=True)
class SymbolSpec:
    """Static contract details for one tradable instrument."""

    symbol: str
    start_price: float
    volatility: float          # per-tick log-return sigma
    tick_size: float
    qty_step: float
    min_qty: float
    quote: str = "USD"

    @property
    def precision(self) -> int:
        return max(0, int(round(-math.log10(self.tick_size))))

    def round_price(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, self.precision)

    def round_qty(self, qty: float) -> float:
        steps = max(1, int(round(qty / self.qty_step)))
        return round(steps * self.qty_step, 8)


SYMBOLS: Dict[str, SymbolSpec] = {
    s.symbol: s
    for s in [
        SymbolSpec("BTCUSDT", 64_250.00, 0.00085, 0.50, 0.001, 0.001, "USDT"),
        SymbolSpec("ETHUSDT", 3_120.00, 0.00110, 0.05, 0.01, 0.01, "USDT"),
        SymbolSpec("EURUSD", 1.08450, 0.00022, 0.00001, 1_000.0, 1_000.0, "USD"),
        SymbolSpec("XAUUSD", 2_338.40, 0.00035, 0.01, 0.10, 0.10, "USD"),
        SymbolSpec("NAS100", 18_420.0, 0.00050, 0.10, 0.10, 0.10, "USD"),
    ]
}


class AccountStatus(str, Enum):
    ACTIVE = "Active"
    WARNING = "Warning"
    DISCONNECTED = "Disconnected"
    KILLED = "Kill switch"


STATUS_ICON = {
    AccountStatus.ACTIVE: "🟢",
    AccountStatus.WARNING: "🟡",
    AccountStatus.DISCONNECTED: "🔴",
    AccountStatus.KILLED: "⛔",
}

# Severity order, used to roll per-account status up to an email session.
STATUS_RANK = {
    AccountStatus.ACTIVE: 0,
    AccountStatus.WARNING: 1,
    AccountStatus.DISCONNECTED: 2,
    AccountStatus.KILLED: 3,
}


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


class ExecStatus(str, Enum):
    FILLED = "FILLED"
    WORKING = "WORKING"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


# Account blueprint. `email` is the session an account is logged in under, and
# is what the sidebar groups by. `copy_ratio` scales the master's quantity.
ACCOUNT_BLUEPRINT: List[dict] = [
    dict(account_id="MASTER-001", email="desk@avid.trading", label="Master book",
         role="master", copy_ratio=1.00, balance=250_000.0, max_dd=8.0),
    dict(account_id="SUB-A1", email="aviv.retail@gmail.com", label="Retail — IBKR",
         role="sub", copy_ratio=0.25, balance=42_000.0, max_dd=10.0),
    dict(account_id="SUB-A2", email="aviv.retail@gmail.com", label="Retail — Binance",
         role="sub", copy_ratio=0.15, balance=18_500.0, max_dd=12.0),
    dict(account_id="SUB-B1", email="prop.desk@fundedfx.io", label="Prop 100k — Phase 2",
         role="sub", copy_ratio=0.50, balance=100_000.0, max_dd=5.0),
    dict(account_id="SUB-B2", email="prop.desk@fundedfx.io", label="Prop 50k — Funded",
         role="sub", copy_ratio=0.30, balance=50_000.0, max_dd=4.0),
    dict(account_id="SUB-B3", email="prop.desk@fundedfx.io", label="Prop 25k — Eval",
         role="sub", copy_ratio=0.20, balance=25_000.0, max_dd=4.0),
    dict(account_id="SUB-C1", email="family.office@avid.trading", label="FO mandate",
         role="sub", copy_ratio=0.75, balance=180_000.0, max_dd=6.0),
    dict(account_id="SUB-D1", email="algo.sandbox@gmail.com", label="Sandbox A",
         role="sub", copy_ratio=0.10, balance=10_000.0, max_dd=20.0),
    dict(account_id="SUB-D2", email="algo.sandbox@gmail.com", label="Sandbox B",
         role="sub", copy_ratio=0.10, balance=10_000.0, max_dd=20.0),
]


# --------------------------------------------------------------------------
# Infrastructure: event log
# --------------------------------------------------------------------------


@dataclass
class LogEntry:
    ts: float
    level: str
    source: str
    message: str


class EventLog:
    """Bounded, thread-safe log. Rendered in the UI instead of stdout."""

    def __init__(self, capacity: int = 500) -> None:
        self._entries: Deque[LogEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def write(self, level: str, source: str, message: str) -> None:
        with self._lock:
            self._entries.append(LogEntry(time.time(), level, source, message))

    def info(self, source: str, message: str) -> None:
        self.write("INFO", source, message)

    def warn(self, source: str, message: str) -> None:
        self.write("WARN", source, message)

    def error(self, source: str, message: str) -> None:
        self.write("ERROR", source, message)

    def tail(self, limit: int = 120) -> List[LogEntry]:
        with self._lock:
            return list(self._entries)[-limit:][::-1]


# --------------------------------------------------------------------------
# Market data: a simulated websocket feed
# --------------------------------------------------------------------------


@dataclass
class Tick:
    ts: float
    price: float
    size: float


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class FeedState(str, Enum):
    CONNECTING = "Connecting"
    LIVE = "Live"
    RECONNECTING = "Reconnecting"
    STOPPED = "Stopped"


class MarketDataFeed:
    """Mock price feed shaped like a websocket client.

    A daemon thread produces ticks on an interval, drops the "connection"
    occasionally, and reconnects with exponential backoff — the same failure
    modes a real feed has, so the UI has to cope with them from day one.

    Replacing this with a real feed means keeping `snapshot`, `last_price`,
    `state` and `subscribe`, and pointing the producer at a real socket.
    """

    def __init__(self, specs: Dict[str, SymbolSpec], log: EventLog) -> None:
        self._specs = specs
        self._log = log
        self._lock = threading.RLock()
        self._ticks: Dict[str, Deque[Tick]] = {
            sym: deque(maxlen=TICK_HISTORY) for sym in specs
        }
        self._last: Dict[str, float] = {sym: spec.start_price for sym, spec in specs.items()}
        self._session_open: Dict[str, float] = dict(self._last)
        self._state = FeedState.CONNECTING
        self._last_tick_ts = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribers: List[Callable[[Dict[str, float]], None]] = []
        self._rng = random.Random(7)
        self._seed_history()

    # -- public API --------------------------------------------------------

    def subscribe(self, callback: Callable[[Dict[str, float]], None]) -> None:
        """Register a per-tick callback (used by the risk engine)."""
        with self._lock:
            self._subscribers.append(callback)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="mock-md-feed", daemon=True
            )
            self._thread.start()
            self._log.info("feed", "Market data thread started")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._state = FeedState.STOPPED

    @property
    def state(self) -> FeedState:
        with self._lock:
            if self._state is FeedState.LIVE and self._is_stale():
                return FeedState.RECONNECTING
            return self._state

    @property
    def last_tick_age(self) -> float:
        with self._lock:
            if not self._last_tick_ts:
                return float("inf")
            return time.time() - self._last_tick_ts

    def last_price(self, symbol: str) -> float:
        with self._lock:
            return self._last.get(symbol, 0.0)

    def marks(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._last)

    def session_change(self, symbol: str) -> Tuple[float, float]:
        """Absolute and percent change since the session open."""
        with self._lock:
            open_px = self._session_open.get(symbol, 0.0)
            last = self._last.get(symbol, 0.0)
        if not open_px:
            return 0.0, 0.0
        return last - open_px, (last - open_px) / open_px * 100.0

    def candles(self, symbol: str, bar_seconds: int, limit: int = 240) -> List[Candle]:
        """Aggregate raw ticks into OHLCV bars of the requested size."""
        with self._lock:
            ticks = list(self._ticks.get(symbol, ()))
        if not ticks:
            return []

        buckets: Dict[int, Candle] = {}
        for tick in ticks:
            bucket = int(tick.ts // bar_seconds) * bar_seconds
            candle = buckets.get(bucket)
            if candle is None:
                buckets[bucket] = Candle(
                    time=bucket,
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=tick.size,
                )
            else:
                candle.high = max(candle.high, tick.price)
                candle.low = min(candle.low, tick.price)
                candle.close = tick.price
                candle.volume += tick.size
        ordered = [buckets[key] for key in sorted(buckets)]
        return ordered[-limit:]

    # -- internals ---------------------------------------------------------

    def _is_stale(self) -> bool:
        return bool(self._last_tick_ts) and (time.time() - self._last_tick_ts) > STALE_AFTER

    def _seed_history(self) -> None:
        """Back-fill ticks so the chart is populated on first paint."""
        now = time.time()
        start = now - SEED_TICKS * TICK_INTERVAL
        prices = {sym: spec.start_price for sym, spec in self._specs.items()}
        for i in range(SEED_TICKS):
            ts = start + i * TICK_INTERVAL
            for sym, spec in self._specs.items():
                prices[sym] = self._next_price(spec, prices[sym])
                self._ticks[sym].append(
                    Tick(ts, prices[sym], round(self._rng.uniform(0.2, 3.0), 3))
                )
        self._last = dict(prices)
        # The "session open" is where the visible history begins.
        for sym in self._specs:
            first = self._ticks[sym][0] if self._ticks[sym] else None
            self._session_open[sym] = first.price if first else prices[sym]

    def _next_price(self, spec: SymbolSpec, price: float) -> float:
        """Geometric random walk with a gentle pull back toward the anchor."""
        shock = self._rng.gauss(0.0, spec.volatility)
        reversion = 0.0008 * math.log(spec.start_price / max(price, 1e-9))
        nxt = price * math.exp(shock + reversion)
        return spec.round_price(max(nxt, spec.tick_size))

    def _run(self) -> None:
        backoff = 1.0
        with self._lock:
            self._state = FeedState.LIVE
        while not self._stop.is_set():
            try:
                # Simulate an occasional dropped connection.
                if self._rng.random() < 0.0015:
                    outage = self._rng.uniform(1.5, 4.0)
                    with self._lock:
                        self._state = FeedState.RECONNECTING
                    self._log.warn("feed", f"Socket closed — reconnecting in {backoff:.1f}s")
                    self._stop.wait(min(outage + backoff, 8.0))
                    backoff = min(backoff * 2, 8.0)
                    with self._lock:
                        self._state = FeedState.LIVE
                    self._log.info("feed", "Reconnected, resuming stream")
                    continue

                backoff = 1.0
                now = time.time()
                with self._lock:
                    for sym, spec in self._specs.items():
                        price = self._next_price(spec, self._last[sym])
                        self._last[sym] = price
                        self._ticks[sym].append(
                            Tick(now, price, round(self._rng.uniform(0.2, 3.0), 3))
                        )
                    self._last_tick_ts = now
                    marks = dict(self._last)
                    subscribers = list(self._subscribers)

                for callback in subscribers:
                    try:
                        callback(marks)
                    except Exception as exc:  # a bad subscriber must not kill the feed
                        self._log.error("feed", f"Tick subscriber failed: {exc!r}")

                self._stop.wait(TICK_INTERVAL)
            except Exception as exc:  # pragma: no cover - defensive
                self._log.error("feed", f"Feed loop error: {exc!r} — backing off")
                self._stop.wait(min(backoff, 5.0))
                backoff = min(backoff * 2, 8.0)


# --------------------------------------------------------------------------
# Accounts, positions and risk
# --------------------------------------------------------------------------


@dataclass
class Position:
    symbol: str
    qty: float = 0.0            # signed: positive long, negative short
    avg_price: float = 0.0
    realized: float = 0.0

    def apply_fill(self, side: Side, qty: float, price: float) -> float:
        """Apply a fill and return the realized PnL it produced."""
        delta = side.sign * qty
        if self.qty == 0.0 or (self.qty > 0) == (delta > 0):
            new_qty = self.qty + delta
            notional = self.avg_price * abs(self.qty) + price * qty
            self.avg_price = notional / abs(new_qty) if new_qty else 0.0
            self.qty = new_qty
            return 0.0

        closing = min(abs(delta), abs(self.qty))
        direction = 1.0 if self.qty > 0 else -1.0
        realized = (price - self.avg_price) * closing * direction
        self.realized += realized
        self.qty += delta
        if abs(self.qty) < 1e-9:
            self.qty = 0.0
            self.avg_price = 0.0
        elif abs(delta) > closing:
            self.avg_price = price     # position reversed
        return realized

    def unrealized(self, mark: float) -> float:
        if not self.qty or not mark:
            return 0.0
        return (mark - self.avg_price) * self.qty


@dataclass
class Account:
    account_id: str
    email: str
    label: str
    role: str
    copy_ratio: float
    starting_balance: float
    max_drawdown_pct: float
    status: AccountStatus = AccountStatus.ACTIVE
    positions: Dict[str, Position] = field(default_factory=dict)
    peak_equity: float = 0.0
    killed_at: Optional[float] = None
    kill_reason: str = ""
    last_heartbeat: float = field(default_factory=time.time)
    fills: int = 0
    rejects: int = 0

    def __post_init__(self) -> None:
        if not self.peak_equity:
            self.peak_equity = self.starting_balance

    # -- derived state -----------------------------------------------------

    @property
    def is_master(self) -> bool:
        return self.role == "master"

    @property
    def tradable(self) -> bool:
        return self.status in (AccountStatus.ACTIVE, AccountStatus.WARNING)

    def position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol))

    def realized_pnl(self) -> float:
        return sum(p.realized for p in self.positions.values())

    def unrealized_pnl(self, marks: Dict[str, float]) -> float:
        return sum(p.unrealized(marks.get(p.symbol, 0.0)) for p in self.positions.values())

    def equity(self, marks: Dict[str, float]) -> float:
        return self.starting_balance + self.realized_pnl() + self.unrealized_pnl(marks)

    def open_positions(self) -> List[Position]:
        return [p for p in self.positions.values() if p.qty]

    def gross_exposure(self, marks: Dict[str, float]) -> float:
        return sum(abs(p.qty) * marks.get(p.symbol, 0.0) for p in self.positions.values())

    def drawdown_pct(self, marks: Dict[str, float]) -> float:
        peak = max(self.peak_equity, 1e-9)
        return max(0.0, (peak - self.equity(marks)) / peak * 100.0)

    def risk_used(self, marks: Dict[str, float]) -> float:
        """Drawdown as a fraction of the account's kill-switch budget."""
        if self.max_drawdown_pct <= 0:
            return 0.0
        return min(1.0, self.drawdown_pct(marks) / self.max_drawdown_pct)


@dataclass
class WorkingOrder:
    order_id: str
    parent_id: str
    account_id: str
    symbol: str
    side: Side
    qty: float
    limit_price: float
    created: float


class Portfolio:
    """Owns every account, the working-order book, and the risk checks."""

    def __init__(self, blueprint: List[dict], log: EventLog) -> None:
        self._lock = threading.RLock()
        self._log = log
        self._rng = random.Random(23)
        self.accounts: Dict[str, Account] = {}
        for spec in blueprint:
            self.accounts[spec["account_id"]] = Account(
                account_id=spec["account_id"],
                email=spec["email"],
                label=spec["label"],
                role=spec["role"],
                copy_ratio=spec["copy_ratio"],
                starting_balance=spec["balance"],
                max_drawdown_pct=spec["max_dd"],
            )
        self.working: Dict[str, WorkingOrder] = {}
        self.global_halt = False

    # -- lookups -----------------------------------------------------------

    @property
    def master(self) -> Account:
        with self._lock:
            for account in self.accounts.values():
                if account.is_master:
                    return account
        raise RuntimeError("no master account configured")

    def subs(self) -> List[Account]:
        with self._lock:
            return [a for a in self.accounts.values() if not a.is_master]

    def emails(self) -> List[str]:
        seen: List[str] = []
        with self._lock:
            for account in self.accounts.values():
                if account.email not in seen:
                    seen.append(account.email)
        return seen

    def by_email(self) -> Dict[str, List[Account]]:
        grouped: Dict[str, List[Account]] = defaultdict(list)
        with self._lock:
            for account in self.accounts.values():
                grouped[account.email].append(account)
        return dict(grouped)

    @staticmethod
    def session_status(accounts: List[Account]) -> AccountStatus:
        return max(accounts, key=lambda a: STATUS_RANK[a.status]).status

    # -- mutation ----------------------------------------------------------

    def apply_fill(self, account_id: str, symbol: str, side: Side,
                   qty: float, price: float) -> float:
        with self._lock:
            account = self.accounts[account_id]
            realized = account.position(symbol).apply_fill(side, qty, price)
            account.fills += 1
            return realized

    def add_working(self, order: WorkingOrder) -> None:
        with self._lock:
            self.working[order.order_id] = order

    def cancel_working(self, order_id: str) -> bool:
        with self._lock:
            return self.working.pop(order_id, None) is not None

    def cancel_all_working(self) -> int:
        with self._lock:
            count = len(self.working)
            self.working.clear()
        if count:
            self._log.warn("risk", f"Cancelled {count} working order(s)")
        return count

    def working_for(self, symbol: str, account_id: Optional[str] = None) -> List[WorkingOrder]:
        with self._lock:
            return [
                o for o in self.working.values()
                if o.symbol == symbol and (account_id is None or o.account_id == account_id)
            ]

    # -- the per-tick risk loop -------------------------------------------

    def on_tick(self, marks: Dict[str, float]) -> None:
        """Called by the feed on every tick: heartbeats, limits, kill switch."""
        with self._lock:
            self._drift_connectivity()
            self._match_working(marks)
            self._evaluate_risk(marks)

    def _drift_connectivity(self) -> None:
        """Random walk of sub-account session health."""
        now = time.time()
        for account in self.accounts.values():
            if account.status is AccountStatus.KILLED:
                continue
            roll = self._rng.random()
            if account.status is AccountStatus.ACTIVE:
                if roll < 0.0008:
                    account.status = AccountStatus.WARNING
                    self._log.warn(account.account_id, "Session latency spike (>800ms)")
                elif roll < 0.0011:
                    account.status = AccountStatus.DISCONNECTED
                    self._log.error(account.account_id, f"Session dropped for {account.email}")
            elif account.status is AccountStatus.WARNING and roll < 0.015:
                account.status = AccountStatus.ACTIVE
                self._log.info(account.account_id, "Latency recovered")
            elif account.status is AccountStatus.DISCONNECTED and roll < 0.010:
                account.status = AccountStatus.ACTIVE
                self._log.info(account.account_id, f"Re-authenticated {account.email}")
            if account.status is not AccountStatus.DISCONNECTED:
                account.last_heartbeat = now

    def _match_working(self, marks: Dict[str, float]) -> None:
        """Fill resting limit orders that the market has traded through."""
        for order in list(self.working.values()):
            mark = marks.get(order.symbol)
            if not mark:
                continue
            touched = (
                (order.side is Side.BUY and mark <= order.limit_price)
                or (order.side is Side.SELL and mark >= order.limit_price)
            )
            if not touched:
                continue
            account = self.accounts.get(order.account_id)
            if account is None or not account.tradable:
                continue
            self.working.pop(order.order_id, None)
            account.position(order.symbol).apply_fill(order.side, order.qty, order.limit_price)
            account.fills += 1
            self._log.info(
                order.account_id,
                f"Limit {order.side.value} {order.qty:g} {order.symbol} "
                f"filled @ {order.limit_price:g}",
            )

    def _evaluate_risk(self, marks: Dict[str, float]) -> None:
        for account in self.accounts.values():
            equity = account.equity(marks)
            account.peak_equity = max(account.peak_equity, equity)
            if account.status is AccountStatus.KILLED:
                continue
            drawdown = account.drawdown_pct(marks)
            if drawdown >= account.max_drawdown_pct:
                self._trip_kill_switch(
                    account, marks,
                    f"Max drawdown breached: {drawdown:.2f}% ≥ {account.max_drawdown_pct:.2f}%",
                )

    def _trip_kill_switch(self, account: Account, marks: Dict[str, float], reason: str) -> None:
        """Flatten everything on an account and lock it out of further routing."""
        for position in list(account.positions.values()):
            if not position.qty:
                continue
            mark = marks.get(position.symbol) or position.avg_price
            side = Side.SELL if position.qty > 0 else Side.BUY
            position.apply_fill(side, abs(position.qty), mark)
        for order_id, order in list(self.working.items()):
            if order.account_id == account.account_id:
                self.working.pop(order_id, None)
        account.status = AccountStatus.KILLED
        account.killed_at = time.time()
        account.kill_reason = reason
        self._log.error(account.account_id, f"KILL SWITCH — {reason}. Positions flattened.")

    def kill(self, account_id: str, marks: Dict[str, float], reason: str) -> None:
        with self._lock:
            account = self.accounts.get(account_id)
            if account and account.status is not AccountStatus.KILLED:
                self._trip_kill_switch(account, marks, reason)

    def kill_all(self, marks: Dict[str, float], reason: str) -> None:
        with self._lock:
            self.global_halt = True
            for account in list(self.accounts.values()):
                if account.status is not AccountStatus.KILLED:
                    self._trip_kill_switch(account, marks, reason)

    def reinstate(self, account_id: str) -> None:
        """Clear a kill switch and re-baseline the drawdown peak."""
        with self._lock:
            account = self.accounts.get(account_id)
            if not account:
                return
            account.status = AccountStatus.ACTIVE
            account.killed_at = None
            account.kill_reason = ""
            account.peak_equity = account.starting_balance + account.realized_pnl()
            self.global_halt = any(
                a.status is AccountStatus.KILLED for a in self.accounts.values()
            )
        self._log.info(account_id, "Kill switch cleared, account re-armed")


# --------------------------------------------------------------------------
# Order routing: master fill + copy distribution
# --------------------------------------------------------------------------


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    qty: float
    order_type: OrderType
    limit_price: Optional[float] = None
    targets: Optional[List[str]] = None      # email sessions to copy into
    note: str = ""


@dataclass
class ExecReport:
    order_id: str
    parent_id: str
    account_id: str
    email: str
    symbol: str
    side: Side
    requested_qty: float
    filled_qty: float
    price: float
    status: ExecStatus
    latency_ms: float
    message: str = ""
    ts: float = field(default_factory=time.time)

    def as_row(self) -> dict:
        return {
            "Time": datetime.fromtimestamp(self.ts, timezone.utc).strftime("%H:%M:%S"),
            "Order": self.order_id,
            "Account": self.account_id,
            "Session": self.email,
            "Symbol": self.symbol,
            "Side": self.side.value,
            "Qty": round(self.filled_qty or self.requested_qty, 6),
            "Price": round(self.price, 6) if self.price else None,
            "Status": self.status.value,
            "Latency (ms)": round(self.latency_ms, 1),
            "Detail": self.message,
        }


class BrokerError(RuntimeError):
    """Raised by the simulated broker adapter; always caught by the router."""


class OrderRouter:
    """Fills the master, then fans the same order out to the sub-accounts.

    The broker call is mocked in `_send_to_broker`. It has latency, it
    randomly rejects, and the router retries with backoff — so the UI path is
    already exercising the error handling a live adapter will need.
    """

    MAX_ATTEMPTS = 3
    REJECT_RATE = 0.06
    SLIPPAGE_TICKS = 3

    def __init__(self, feed: MarketDataFeed, portfolio: Portfolio, log: EventLog) -> None:
        self._feed = feed
        self._portfolio = portfolio
        self._log = log
        self._rng = random.Random(101)
        self.blotter: Deque[ExecReport] = deque(maxlen=400)

    # -- public API --------------------------------------------------------

    def submit(self, request: OrderRequest) -> List[ExecReport]:
        """Route one parent order. Never raises — failures come back as reports."""
        parent_id = uuid.uuid4().hex[:8].upper()
        reports: List[ExecReport] = []
        try:
            self._validate(request)
        except ValueError as exc:
            report = self._report(parent_id, self._portfolio.master, request,
                                  ExecStatus.REJECTED, request.qty, 0.0, 0.0, str(exc),
                                  latency=0.0)
            self._record([report])
            return [report]

        if self._portfolio.global_halt:
            report = self._report(parent_id, self._portfolio.master, request,
                                  ExecStatus.REJECTED, request.qty, 0.0, 0.0,
                                  "Desk-wide halt is engaged", latency=0.0)
            self._record([report])
            return [report]

        master = self._portfolio.master
        master_report = self._execute(parent_id, master, request, request.qty)
        reports.append(master_report)

        # A master that did not get done must not leak copies into the subs.
        if master_report.status in (ExecStatus.REJECTED, ExecStatus.SKIPPED):
            self._log.error(
                "router",
                f"{parent_id}: master {master_report.status.value} — copy distribution aborted",
            )
            self._record(reports)
            return reports

        targets = set(request.targets or self._portfolio.emails())
        for account in self._portfolio.subs():
            if account.email not in targets:
                continue
            child_qty = self.child_qty(request.symbol, request.qty, account.copy_ratio)
            reports.append(self._execute(parent_id, account, request, child_qty))

        filled = sum(1 for r in reports if r.status is ExecStatus.FILLED)
        working = sum(1 for r in reports if r.status is ExecStatus.WORKING)
        self._log.info(
            "router",
            f"{parent_id}: {request.side.value} {request.qty:g} {request.symbol} → "
            f"{filled} filled, {working} working, {len(reports) - filled - working} not done",
        )
        self._record(reports)
        return reports

    def flatten(self, account_id: str, symbol: Optional[str] = None) -> List[ExecReport]:
        """Close open positions at the mark. Used by the UI's panic buttons."""
        account = self._portfolio.accounts.get(account_id)
        reports: List[ExecReport] = []
        if account is None:
            return reports
        parent_id = uuid.uuid4().hex[:8].upper()
        for position in account.open_positions():
            if symbol and position.symbol != symbol:
                continue
            side = Side.SELL if position.qty > 0 else Side.BUY
            request = OrderRequest(position.symbol, side, abs(position.qty),
                                   OrderType.MARKET, note="flatten")
            reports.append(self._execute(parent_id, account, request, abs(position.qty)))
        self._record(reports)
        return reports

    # -- internals ---------------------------------------------------------

    def _validate(self, request: OrderRequest) -> None:
        spec = SYMBOLS.get(request.symbol)
        if spec is None:
            raise ValueError(f"Unknown symbol {request.symbol}")
        if request.qty <= 0:
            raise ValueError("Quantity must be greater than zero")
        if request.qty < spec.min_qty:
            raise ValueError(f"Quantity below minimum of {spec.min_qty:g}")
        if request.order_type is OrderType.LIMIT:
            if not request.limit_price or request.limit_price <= 0:
                raise ValueError("Limit orders need a positive limit price")

    def child_qty(self, symbol: str, parent_qty: float, ratio: float) -> float:
        spec = SYMBOLS[symbol]
        return max(spec.min_qty, spec.round_qty(parent_qty * ratio))

    def _execute(self, parent_id: str, account: Account, request: OrderRequest,
                 qty: float) -> ExecReport:
        if account.status is AccountStatus.KILLED:
            return self._report(parent_id, account, request, ExecStatus.SKIPPED, qty,
                                0.0, 0.0, f"Kill switch engaged: {account.kill_reason}",
                                latency=0.0)
        if account.status is AccountStatus.DISCONNECTED:
            return self._report(parent_id, account, request, ExecStatus.SKIPPED, qty,
                                0.0, 0.0, f"Session {account.email} is disconnected",
                                latency=0.0)

        started = time.perf_counter()
        last_error = "unknown broker error"
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                price = self._send_to_broker(account, request, qty)
                latency = (time.perf_counter() - started) * 1000.0
                if request.order_type is OrderType.LIMIT:
                    order = WorkingOrder(
                        order_id=uuid.uuid4().hex[:8].upper(),
                        parent_id=parent_id,
                        account_id=account.account_id,
                        symbol=request.symbol,
                        side=request.side,
                        qty=qty,
                        limit_price=price,
                        created=time.time(),
                    )
                    self._portfolio.add_working(order)
                    return self._report(parent_id, account, request, ExecStatus.WORKING,
                                        qty, 0.0, price, f"Resting @ {price:g}",
                                        order.order_id, latency)
                self._portfolio.apply_fill(account.account_id, request.symbol,
                                           request.side, qty, price)
                detail = "" if attempt == 1 else f"filled on attempt {attempt}"
                return self._report(parent_id, account, request, ExecStatus.FILLED,
                                    qty, qty, price, detail, latency=latency)
            except BrokerError as exc:
                last_error = str(exc)
                if attempt < self.MAX_ATTEMPTS:
                    self._log.warn(
                        account.account_id,
                        f"{parent_id}: {last_error} — retry {attempt}/{self.MAX_ATTEMPTS - 1}",
                    )
                    time.sleep(min(0.05 * (2 ** (attempt - 1)), 0.2))
            except Exception as exc:  # pragma: no cover - defensive
                last_error = f"unexpected adapter failure: {exc!r}"
                break

        account.rejects += 1
        latency = (time.perf_counter() - started) * 1000.0
        if account.status is AccountStatus.ACTIVE:
            account.status = AccountStatus.WARNING
        self._log.error(account.account_id, f"{parent_id}: order rejected — {last_error}")
        return self._report(parent_id, account, request, ExecStatus.REJECTED, qty,
                            0.0, 0.0, last_error, latency=latency)

    def _send_to_broker(self, account: Account, request: OrderRequest, qty: float) -> float:
        """Stand-in for a real broker adapter. Replace this, keep the signature."""
        time.sleep(self._rng.uniform(0.005, 0.03))     # simulated round trip
        if self._rng.random() < self.REJECT_RATE:
            raise BrokerError(
                self._rng.choice([
                    "broker timeout (no ack within 2000ms)",
                    "insufficient margin on venue",
                    "session token expired",
                    "venue rejected: price outside limits",
                ])
            )
        spec = SYMBOLS[request.symbol]
        if request.order_type is OrderType.LIMIT and request.limit_price:
            return spec.round_price(request.limit_price)

        mark = self._feed.last_price(request.symbol)
        if not mark:
            raise BrokerError("no market data for symbol")
        slip = self._rng.randint(0, self.SLIPPAGE_TICKS) * spec.tick_size * request.side.sign
        return spec.round_price(mark + slip)

    def _report(self, parent_id: str, account: Account, request: OrderRequest,
                status: ExecStatus, requested: float, filled: float, price: float,
                message: str, order_id: Optional[str] = None,
                latency: Optional[float] = None) -> ExecReport:
        return ExecReport(
            order_id=order_id or uuid.uuid4().hex[:8].upper(),
            parent_id=parent_id,
            account_id=account.account_id,
            email=account.email,
            symbol=request.symbol,
            side=request.side,
            requested_qty=requested,
            filled_qty=filled,
            price=price,
            status=status,
            latency_ms=latency if latency is not None else 0.0,
            message=message,
        )

    def _record(self, reports: List[ExecReport]) -> None:
        for report in reports:
            self.blotter.append(report)


# --------------------------------------------------------------------------
# Engine: one object that owns the feed, the book and the router
# --------------------------------------------------------------------------


class TradingEngine:
    def __init__(self) -> None:
        self.log = EventLog()
        self.feed = MarketDataFeed(SYMBOLS, self.log)
        self.portfolio = Portfolio(ACCOUNT_BLUEPRINT, self.log)
        self.router = OrderRouter(self.feed, self.portfolio, self.log)
        self.feed.subscribe(self.portfolio.on_tick)
        self.started_at = time.time()

    def start(self) -> "TradingEngine":
        self.feed.start()
        self.log.info("engine", "Desk online — mock feed, mock brokers, no live credentials")
        return self

    def marks(self) -> Dict[str, float]:
        return self.feed.marks()

    def desk_equity(self, marks: Dict[str, float]) -> float:
        return sum(a.equity(marks) for a in self.portfolio.accounts.values())

    def desk_open_pnl(self, marks: Dict[str, float]) -> float:
        return sum(a.unrealized_pnl(marks) for a in self.portfolio.accounts.values())

    def desk_realized(self) -> float:
        return sum(a.realized_pnl() for a in self.portfolio.accounts.values())


@st.cache_resource(show_spinner=False)
def get_engine() -> TradingEngine:
    """One engine per server process, shared by every browser session."""
    return TradingEngine().start()


# --------------------------------------------------------------------------
# Chart component (TradingView Lightweight Charts, injected as HTML/JS)
# --------------------------------------------------------------------------

_CHART_HTML = """
<div id="wrapper">
  <div id="chart"></div>
  <div id="fallback" class="hidden">
    Chart library could not be loaded. Check the network connection to
    cdn.jsdelivr.net, or vendor lightweight-charts locally.
  </div>
</div>
<style>
  html, body { margin: 0; padding: 0; background: #0e1117; }
  #wrapper { position: relative; width: 100%; height: __HEIGHT__px; }
  #chart { width: 100%; height: 100%; }
  #fallback {
    position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; text-align: center; padding: 0 24px;
    color: #c8ccd6; background: #0e1117; font: 13px/1.6 system-ui, sans-serif;
  }
  .hidden { display: none; }
</style>
<script src="__CDN__" onerror="window.__chartLibFailed = true;"></script>
<script>
(function () {
  var payload = __PAYLOAD__;
  var box = document.getElementById("chart");
  var fallback = document.getElementById("fallback");

  if (window.__chartLibFailed || typeof LightweightCharts === "undefined") {
    fallback.classList.remove("hidden");
    return;
  }

  try {
    var chart = LightweightCharts.createChart(box, {
      width: box.clientWidth,
      height: payload.height,
      layout: {
        background: { type: "solid", color: "#0e1117" },
        textColor: "#b8bdc9",
        fontSize: 11
      },
      grid: {
        vertLines: { color: "rgba(120,130,150,0.10)" },
        horzLines: { color: "rgba(120,130,150,0.10)" }
      },
      rightPriceScale: {
        borderColor: "rgba(120,130,150,0.25)",
        scaleMargins: { top: 0.08, bottom: 0.26 }
      },
      timeScale: {
        borderColor: "rgba(120,130,150,0.25)",
        timeVisible: true,
        secondsVisible: payload.bar_seconds < 60,
        rightOffset: 4
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      watermark: {
        visible: true,
        text: payload.symbol + "  ·  " + payload.timeframe,
        color: "rgba(150,160,180,0.10)",
        fontSize: 42,
        horzAlign: "center",
        vertAlign: "center"
      }
    });

    var candles = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
      priceFormat: {
        type: "price",
        precision: payload.precision,
        minMove: payload.tick_size
      }
    });
    candles.setData(payload.candles);

    var volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume"
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.80, bottom: 0.0 }
    });
    volume.setData(payload.volume);

    if (payload.markers && payload.markers.length) {
      candles.setMarkers(payload.markers);
    }
    (payload.price_lines || []).forEach(function (line) {
      candles.createPriceLine({
        price: line.price,
        color: line.color,
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: line.title
      });
    });

    // The component iframe reloads on every Streamlit rerun, so the zoom
    // level is persisted and re-applied instead of snapping back each tick.
    var zoomKey = "avid.barSpacing." + payload.symbol + "." + payload.timeframe;
    try {
      var saved = parseFloat(window.sessionStorage.getItem(zoomKey));
      if (saved && saved > 0) {
        chart.timeScale().applyOptions({ barSpacing: saved });
      } else {
        chart.timeScale().fitContent();
      }
    } catch (err) {
      chart.timeScale().fitContent();
    }
    chart.timeScale().scrollToRealTime();

    var saveTimer = null;
    chart.timeScale().subscribeVisibleLogicalRangeChange(function () {
      if (saveTimer) { return; }
      saveTimer = setTimeout(function () {
        saveTimer = null;
        try {
          var opts = chart.timeScale().options();
          window.sessionStorage.setItem(zoomKey, String(opts.barSpacing));
        } catch (err) { /* private browsing — zoom just won't persist */ }
      }, 250);
    });

    window.addEventListener("resize", function () {
      chart.applyOptions({ width: box.clientWidth });
    });
  } catch (err) {
    fallback.textContent = "Chart failed to render: " + err;
    fallback.classList.remove("hidden");
  }
})();
</script>
"""


def render_chart(engine: TradingEngine, symbol: str, timeframe: str, height: int = 460) -> None:
    """Draw the live candle chart with fills marked and working orders lined."""
    spec = SYMBOLS[symbol]
    bar_seconds = TIMEFRAMES[timeframe]
    candles = engine.feed.candles(symbol, bar_seconds)
    if not candles:
        st.info("Waiting for the first ticks from the feed…")
        return

    bars = [
        dict(time=c.time, open=c.open, high=c.high, low=c.low, close=c.close)
        for c in candles
    ]
    volume = [
        dict(
            time=c.time,
            value=round(c.volume, 3),
            color="rgba(38,166,154,0.45)" if c.close >= c.open else "rgba(239,83,80,0.45)",
        )
        for c in candles
    ]

    first_bar = candles[0].time
    markers = []
    for report in list(engine.router.blotter):
        if report.symbol != symbol or report.status is not ExecStatus.FILLED:
            continue
        if report.account_id != engine.portfolio.master.account_id:
            continue          # master fills only, or the chart turns into confetti
        bar_time = int(report.ts // bar_seconds) * bar_seconds
        if bar_time < first_bar:
            continue
        buy = report.side is Side.BUY
        markers.append(dict(
            time=bar_time,
            position="belowBar" if buy else "aboveBar",
            color="#26a69a" if buy else "#ef5350",
            shape="arrowUp" if buy else "arrowDown",
            text=f"{report.side.value} {report.filled_qty:g} @ {report.price:g}",
        ))
    markers.sort(key=lambda m: m["time"])

    price_lines = []
    master_position = engine.portfolio.master.positions.get(symbol)
    if master_position and master_position.qty:
        price_lines.append(dict(
            price=master_position.avg_price,
            color="#f0b90b",
            title=f"avg {master_position.qty:+g}",
        ))
    for order in engine.portfolio.working_for(symbol, engine.portfolio.master.account_id):
        price_lines.append(dict(
            price=order.limit_price,
            color="#7aa2f7",
            title=f"{order.side.value} limit {order.qty:g}",
        ))

    payload = dict(
        symbol=symbol,
        timeframe=timeframe,
        bar_seconds=bar_seconds,
        precision=spec.precision,
        tick_size=spec.tick_size,
        height=height,
        candles=bars,
        volume=volume,
        markers=markers[-60:],
        price_lines=price_lines[:8],
    )

    html = (
        _CHART_HTML
        .replace("__CDN__", CHART_CDN)
        .replace("__HEIGHT__", str(height))
        .replace("__PAYLOAD__", json.dumps(payload))
    )
    components.html(html, height=height + 8, scrolling=False)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


def money(value: float) -> str:
    return f"${value:,.2f}"


def signed_money(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S")


def feed_badge(engine: TradingEngine) -> str:
    state = engine.feed.state
    age = engine.feed.last_tick_age
    icon = {"Live": "🟢", "Reconnecting": "🟠", "Connecting": "🟡", "Stopped": "⚫"}
    suffix = "" if age == float("inf") else f" · last tick {age:.1f}s ago"
    return f"{icon.get(state.value, '⚪')} Feed: {state.value}{suffix}"


# --------------------------------------------------------------------------
# Sidebar: multi-account portfolio and risk monitor
# --------------------------------------------------------------------------


def render_sidebar(engine: TradingEngine, marks: Dict[str, float]) -> None:
    portfolio = engine.portfolio
    sidebar = st.sidebar
    sidebar.title("Accounts & risk")

    accounts = list(portfolio.accounts.values())
    by_status: Dict[AccountStatus, int] = defaultdict(int)
    for account in accounts:
        by_status[account.status] += 1

    equity = engine.desk_equity(marks)
    open_pnl = engine.desk_open_pnl(marks)

    col_a, col_b = sidebar.columns(2)
    col_a.metric("Desk equity", money(equity), signed_money(open_pnl))
    col_b.metric(
        "Sessions live",
        f"{by_status[AccountStatus.ACTIVE]}/{len(accounts)}",
        f"{by_status[AccountStatus.KILLED]} killed" if by_status[AccountStatus.KILLED] else None,
        delta_color="inverse",
    )

    sidebar.caption(
        " · ".join(
            f"{STATUS_ICON[status]} {by_status[status]} {status.value}"
            for status in AccountStatus
            if by_status[status]
        )
        or "No accounts configured"
    )

    if portfolio.global_halt:
        sidebar.error("Desk-wide halt engaged — new orders are blocked.")

    halt_col, resume_col = sidebar.columns(2)
    if halt_col.button("🛑 Halt all", use_container_width=True,
                       help="Flatten every account and block new orders"):
        portfolio.kill_all(marks, "Manual desk-wide halt")
        st.rerun()
    if resume_col.button("♻️ Re-arm all", use_container_width=True,
                         help="Clear kill switches and re-baseline drawdown peaks"):
        for account in accounts:
            portfolio.reinstate(account.account_id)
        portfolio.global_halt = False
        st.rerun()

    sidebar.divider()

    show_only_open = sidebar.toggle("Only accounts with exposure", value=False)

    for email, members in portfolio.by_email().items():
        members = sorted(members, key=lambda a: (not a.is_master, a.account_id))
        if show_only_open and not any(a.open_positions() for a in members):
            continue
        status = Portfolio.session_status(members)
        session_equity = sum(a.equity(marks) for a in members)
        header = f"{STATUS_ICON[status]} {email} · {money(session_equity)}"
        with sidebar.expander(header, expanded=True):
            st.caption(f"Session status: {status.value} · {len(members)} account(s)")
            for account in members:
                _render_account_card(engine, account, marks)


def _render_account_card(engine: TradingEngine, account: Account,
                         marks: Dict[str, float]) -> None:
    equity = account.equity(marks)
    open_pnl = account.unrealized_pnl(marks)
    drawdown = account.drawdown_pct(marks)
    used = account.risk_used(marks)
    positions = account.open_positions()

    title = f"{STATUS_ICON[account.status]} **{account.account_id}** — {account.label}"
    if account.is_master:
        title += " · `master`"
    st.markdown(title)

    left, right = st.columns(2)
    left.metric("Equity", money(equity), signed_money(open_pnl), label_visibility="visible")
    right.metric("Copy ratio", f"{account.copy_ratio:.0%}",
                 f"{len(positions)} open" if positions else "flat",
                 delta_color="off")

    bar_label = (
        f"Drawdown {drawdown:.2f}% / {account.max_drawdown_pct:.2f}% limit"
        if account.status is not AccountStatus.KILLED
        else f"KILLED — {account.kill_reason}"
    )
    try:
        st.progress(min(max(used, 0.0), 1.0), text=bar_label)
    except TypeError:                      # Streamlit < 1.18 has no progress text
        st.progress(min(max(used, 0.0), 1.0))
        st.caption(bar_label)

    if account.status is AccountStatus.KILLED:
        st.error(account.kill_reason or "Kill switch engaged")
    elif used >= 0.75:
        st.warning(f"{used:.0%} of the drawdown budget is used.")
    elif account.status is AccountStatus.DISCONNECTED:
        st.warning(f"No heartbeat for {time.time() - account.last_heartbeat:.0f}s.")

    if positions:
        rows = [
            {
                "Symbol": p.symbol,
                "Qty": round(p.qty, 6),
                "Avg": round(p.avg_price, SYMBOLS[p.symbol].precision)
                if p.symbol in SYMBOLS else round(p.avg_price, 4),
                "PnL": round(p.unrealized(marks.get(p.symbol, 0.0)), 2),
            }
            for p in positions
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    controls = st.columns(2)
    if controls[0].button("Flatten", key=f"flat-{account.account_id}",
                          use_container_width=True, disabled=not positions):
        engine.router.flatten(account.account_id)
        st.rerun()
    if account.status is AccountStatus.KILLED:
        if controls[1].button("Re-arm", key=f"arm-{account.account_id}",
                              use_container_width=True):
            engine.portfolio.reinstate(account.account_id)
            st.rerun()
    else:
        if controls[1].button("Kill", key=f"kill-{account.account_id}",
                              use_container_width=True):
            engine.portfolio.kill(account.account_id, marks, "Manual kill switch")
            st.rerun()
    st.markdown("---")


# --------------------------------------------------------------------------
# Order execution panel
# --------------------------------------------------------------------------


def render_order_panel(engine: TradingEngine, symbol: str, marks: Dict[str, float]) -> None:
    spec = SYMBOLS[symbol]
    portfolio = engine.portfolio
    mark = marks.get(symbol, 0.0)

    st.subheader("Execution")
    # The ticket always trades the charted instrument: one source of truth
    # keeps the quantity step, tick size and limit default in sync with the
    # symbol the trader is actually looking at.
    order_symbol = symbol
    st.caption(f"Ticket armed on **{order_symbol}** — switch instrument above to retarget.")

    # Deliberately not an st.form: a trading ticket should re-price its
    # notional preview as the trader types, not only on submit.
    top = st.columns([1, 1])
    order_type = OrderType(
        top[0].selectbox("Order type", [t.value for t in OrderType],
                         key=f"otype-{order_symbol}")
    )
    qty = top[1].number_input(
        "Quantity / lots",
        min_value=float(spec.min_qty),
        value=float(max(spec.min_qty, spec.qty_step * 10)),
        step=float(spec.qty_step),
        format="%.4f",
        key=f"qty-{order_symbol}",
    )

    bottom = st.columns([1.2, 1, 1])
    limit_price = bottom[0].number_input(
        "Limit price",
        min_value=0.0,
        value=float(round(mark, spec.precision)),
        step=float(spec.tick_size),
        format=f"%.{spec.precision}f",
        disabled=order_type is OrderType.MARKET,
        help="Ignored for market orders. Resting orders fill when the mark trades through.",
        key=f"limit-{order_symbol}",
    )
    copy_enabled = bottom[1].checkbox(
        "Copy to sub-accounts", value=True, key="copy-enabled",
        help="Off means the order only touches the master book.",
    )
    bottom[2].text_input("Tag", key="order-tag", placeholder="optional note")

    sessions = [e for e in portfolio.emails() if e != portfolio.master.email]
    targets = st.multiselect(
        "Target email sessions", sessions, default=sessions, key="copy-targets",
        disabled=not copy_enabled,
        help="Each session can hold several sub-accounts; every one of them "
             "gets the order scaled by its own copy ratio.",
    )

    eligible = [
        a for a in portfolio.subs()
        if copy_enabled and a.email in targets and a.tradable
    ]
    child_total = sum(
        engine.router.child_qty(order_symbol, qty, a.copy_ratio) for a in eligible
    )
    st.caption(
        f"Master {qty:g} {order_symbol} ≈ {money(qty * mark)} notional · "
        f"copies to {len(eligible)} tradable account(s) for {child_total:g} "
        f"{order_symbol} ≈ {money(child_total * mark)}"
    )

    blocked = portfolio.global_halt or portfolio.master.status is AccountStatus.KILLED
    if blocked:
        st.error("Master account is halted — clear the kill switch to trade.")

    buy_col, sell_col = st.columns(2)
    buy = buy_col.button("🟩  BUY / LONG", use_container_width=True,
                         type="primary", disabled=blocked, key="btn-buy")
    sell = sell_col.button("🟥  SELL / SHORT", use_container_width=True,
                           disabled=blocked, key="btn-sell")

    if not (buy or sell):
        return

    request = OrderRequest(
        symbol=order_symbol,
        side=Side.BUY if buy else Side.SELL,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price if order_type is OrderType.LIMIT else None,
        targets=targets if copy_enabled else [portfolio.master.email],
        note=st.session_state.get("order-tag", ""),
    )
    try:
        reports = engine.router.submit(request)
    except Exception as exc:  # the router should never raise, but the UI must survive it
        engine.log.error("ui", f"Order submission crashed: {exc!r}")
        st.error(f"Order submission failed: {exc}")
        return

    st.session_state["last_reports"] = [r.as_row() for r in reports]
    filled = [r for r in reports if r.status is ExecStatus.FILLED]
    working = [r for r in reports if r.status is ExecStatus.WORKING]
    failed = [r for r in reports if r.status in (ExecStatus.REJECTED, ExecStatus.SKIPPED)]

    headline = (
        f"{request.side.value} {qty:g} {order_symbol} — "
        f"{len(filled)} filled, {len(working)} working, {len(failed)} not done"
    )
    if failed and not (filled or working):
        st.error(headline)
    elif failed:
        st.warning(headline)
    else:
        st.success(headline)


def render_last_execution() -> None:
    rows = st.session_state.get("last_reports")
    if not rows:
        return
    with st.expander("Last order — per-account distribution", expanded=True):
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# Blotter, positions, working orders, log
# --------------------------------------------------------------------------


def render_tables(engine: TradingEngine, marks: Dict[str, float]) -> None:
    portfolio = engine.portfolio
    tabs = st.tabs(["Positions", "Blotter", "Working orders", "System log"])

    with tabs[0]:
        rows = []
        for account in portfolio.accounts.values():
            for position in account.open_positions():
                mark = marks.get(position.symbol, 0.0)
                rows.append({
                    "Account": account.account_id,
                    "Session": account.email,
                    "Status": account.status.value,
                    "Symbol": position.symbol,
                    "Side": "LONG" if position.qty > 0 else "SHORT",
                    "Qty": round(abs(position.qty), 6),
                    "Avg price": round(position.avg_price, 6),
                    "Mark": round(mark, 6),
                    "Open PnL": round(position.unrealized(mark), 2),
                    "Realized": round(position.realized, 2),
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.caption("Every account is flat.")

    with tabs[1]:
        blotter = list(engine.router.blotter)[::-1]
        if blotter:
            st.dataframe(
                pd.DataFrame([r.as_row() for r in blotter[:200]]),
                hide_index=True, use_container_width=True, height=320,
            )
        else:
            st.caption("No orders routed yet.")

    with tabs[2]:
        working = list(portfolio.working.values())
        if working:
            st.dataframe(
                pd.DataFrame([{
                    "Order": o.order_id,
                    "Parent": o.parent_id,
                    "Account": o.account_id,
                    "Symbol": o.symbol,
                    "Side": o.side.value,
                    "Qty": round(o.qty, 6),
                    "Limit": round(o.limit_price, 6),
                    "Distance": round(marks.get(o.symbol, 0.0) - o.limit_price, 6),
                    "Age (s)": round(time.time() - o.created, 1),
                } for o in working]),
                hide_index=True, use_container_width=True,
            )
            if st.button("Cancel all working orders"):
                portfolio.cancel_all_working()
                st.rerun()
        else:
            st.caption("No resting orders.")

    with tabs[3]:
        entries = engine.log.tail(150)
        if entries:
            st.dataframe(
                pd.DataFrame([{
                    "Time": clock(e.ts),
                    "Level": e.level,
                    "Source": e.source,
                    "Message": e.message,
                } for e in entries]),
                hide_index=True, use_container_width=True, height=320,
            )
        else:
            st.caption("Nothing logged yet.")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


def render_header(engine: TradingEngine, symbol: str, marks: Dict[str, float]) -> None:
    spec = SYMBOLS[symbol]
    mark = marks.get(symbol, 0.0)
    change, change_pct = engine.feed.session_change(symbol)
    master = engine.portfolio.master
    position = master.positions.get(symbol)

    cols = st.columns(5)
    cols[0].metric(symbol, f"{mark:,.{spec.precision}f}",
                   f"{change:+,.{spec.precision}f} ({change_pct:+.2f}%)")
    cols[1].metric("Desk equity", money(engine.desk_equity(marks)),
                   signed_money(engine.desk_open_pnl(marks)))
    cols[2].metric("Realized (session)", signed_money(engine.desk_realized()))
    cols[3].metric("Master position",
                   f"{position.qty:+g}" if position and position.qty else "flat",
                   f"avg {position.avg_price:,.{spec.precision}f}"
                   if position and position.qty else None,
                   delta_color="off")
    cols[4].metric("Working orders", str(len(engine.portfolio.working)))


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📈", layout="wide",
                       initial_sidebar_state="expanded")

    try:
        engine = get_engine()
    except Exception as exc:  # pragma: no cover - the app must show why it is dead
        st.error(f"Trading engine failed to start: {exc}")
        st.stop()
        return

    # A long-lived server can outlive its feed thread; restart it rather than
    # silently serving a frozen chart.
    if engine.feed.state is FeedState.STOPPED:
        engine.feed.start()

    st.title(f"📈 {APP_TITLE}")
    st.caption(APP_CAPTION)

    controls = st.columns([1.1, 1, 1, 1.4, 1.6])
    symbol = controls[0].selectbox("Instrument", list(SYMBOLS), key="chart-symbol")
    timeframe = controls[1].selectbox(
        "Timeframe", list(TIMEFRAMES),
        index=list(TIMEFRAMES).index(DEFAULT_TIMEFRAME), key="chart-timeframe",
    )
    live = controls[2].toggle("Live", value=True, key="live-mode",
                              help="Auto-refresh the page from the simulated feed")
    interval = controls[3].slider("Refresh (s)", 0.5, 5.0, 1.0, 0.5, key="refresh-interval")
    controls[4].markdown(
        f"<div style='padding-top:1.9rem'>{feed_badge(engine)}</div>",
        unsafe_allow_html=True,
    )

    marks = engine.marks()

    try:
        render_sidebar(engine, marks)
    except Exception as exc:  # one bad account card must not blank the whole page
        engine.log.error("ui", f"Sidebar render failed: {exc!r}")
        st.sidebar.error(f"Account panel failed to render: {exc}")

    render_header(engine, symbol, marks)

    chart_col, ticket_col = st.columns([2.05, 1])
    with chart_col:
        try:
            render_chart(engine, symbol, timeframe)
        except Exception as exc:
            engine.log.error("ui", f"Chart render failed: {exc!r}")
            st.error(f"Chart unavailable: {exc}")
    with ticket_col:
        try:
            render_order_panel(engine, symbol, marks)
        except Exception as exc:
            engine.log.error("ui", f"Order panel failed: {exc!r}")
            st.error(f"Order panel unavailable: {exc}")

    render_last_execution()
    render_tables(engine, marks)

    st.caption(
        "Simulated market data and simulated broker responses. No live "
        "credentials, no real orders. Swap `MarketDataFeed` and `OrderRouter` "
        "to go live."
    )

    if live:
        # Cheap polling loop: sleep, then rerun. Streamlit queues any widget
        # interaction that lands during the sleep, so the UI stays responsive.
        time.sleep(float(interval))
        st.rerun()


if __name__ == "__main__":
    main()
