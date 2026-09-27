"""Durable account state in SQLite, so a restart does not forget today's losses.

Each account's state is stored as one JSON document (easy to evolve without
migrations) plus an append-only ``risk_events`` table that records every halt,
reset and override for the audit trail a prop firm dispute will ask for.

A state row that cannot be read raises :class:`StateCorruptError` instead of
being replaced with a fresh one: silently resetting would hand the bot a full
daily loss allowance it has already spent.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from .logger import get_logger
from .time_utils import ensure_utc, utc_now

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_state (
    account_id  TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_events_account ON risk_events (account_id, id);
CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    account_id   TEXT NOT NULL,
    trade_id     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    direction    TEXT,
    entry_price  REAL,
    stop_price   REAL,
    take_profit  REAL,
    quantity     REAL,
    risk         REAL NOT NULL,
    opened_at    TEXT NOT NULL,
    exit_price   REAL,
    realized_pnl REAL,
    exit_reason  TEXT,
    closed_at    TEXT,
    PRIMARY KEY (account_id, trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades (opened_at);
CREATE TABLE IF NOT EXISTS control_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    action       TEXT NOT NULL,
    argument     TEXT NOT NULL DEFAULT '',
    operator     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    claimed_at   TEXT,
    completed_at TEXT,
    ok           INTEGER,
    result       TEXT
);
"""


class StateStoreError(RuntimeError):
    """The state database could not be opened, read or written."""


class StateCorruptError(StateStoreError):
    """A stored account state exists but cannot be decoded."""


@dataclass(frozen=True)
class RiskEventRecord:
    account_id: str
    ts: datetime
    kind: str
    message: str


@dataclass(frozen=True)
class TradeRecord:
    account_id: str
    trade_id: str
    symbol: str
    direction: str | None
    entry_price: float | None
    stop_price: float | None
    take_profit: float | None
    quantity: float | None
    risk: float
    opened_at: datetime
    exit_price: float | None = None
    realized_pnl: float | None = None
    exit_reason: str | None = None
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True)
class ControlRequest:
    id: int
    account_id: str
    action: str
    argument: str
    operator: str
    created_at: datetime
    completed_at: datetime | None = None
    ok: bool | None = None
    result: str | None = None


_TRADE_COLUMNS = (
    "account_id, trade_id, symbol, direction, entry_price, stop_price, take_profit, "
    "quantity, risk, opened_at, exit_price, realized_pnl, exit_reason, closed_at"
)
_CONTROL_COLUMNS = "id, account_id, action, argument, operator, created_at, completed_at, ok, result"


def _ts(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _trade(row: tuple[Any, ...]) -> TradeRecord:
    opened = _ts(row[9])
    assert opened is not None
    return TradeRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
                       float(row[8]), opened, row[10], row[11], row[12], _ts(row[13]))


def _control(row: tuple[Any, ...]) -> ControlRequest:
    created = _ts(row[5])
    assert created is not None
    return ControlRequest(int(row[0]), row[1], row[2], row[3], row[4], created, _ts(row[6]),
                          None if row[7] is None else bool(row[7]), row[8])


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit mode; writes are wrapped in explicit transactions.
            self._conn = sqlite3.connect(
                str(self.path), timeout=10, isolation_level=None, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            # FULL: a committed halt must survive a power cut on the VPS.
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.executescript(SCHEMA)
        except (sqlite3.Error, OSError) as exc:
            raise StateStoreError(f"cannot open state database {self.path}: {exc}") from exc

    # ------------------------------------------------------------- accounts
    def load_account(self, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT state_json FROM account_state WHERE account_id = ?", (account_id,)
                ).fetchone()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot read state for {account_id}: {exc}") from exc
        if row is None:
            return None
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise StateCorruptError(f"state for {account_id} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise StateCorruptError(f"state for {account_id} is not a JSON object")
        return cast("dict[str, Any]", data)

    def save_account(self, account_id: str, state: dict[str, Any]) -> None:
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"))
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO account_state (account_id, state_json, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
                    "state_json = excluded.state_json, updated_at = excluded.updated_at",
                    (account_id, payload, utc_now().isoformat()),
                )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot save state for {account_id}: {exc}") from exc

    def account_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT account_id FROM account_state ORDER BY account_id")
            return [r[0] for r in rows.fetchall()]

    # --------------------------------------------------------------- events
    def append_event(
        self, account_id: str, kind: str, message: str, ts: datetime | None = None
    ) -> None:
        when = ensure_utc(ts) if ts is not None else utc_now()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO risk_events (account_id, ts, kind, message) VALUES (?, ?, ?, ?)",
                    (account_id, when.isoformat(), kind, message),
                )
            except sqlite3.Error as exc:
                # The audit trail must not take the risk engine down with it.
                log.error("Could not record risk event %s for %s: %s", kind, account_id, exc)

    def recent_events(self, account_id: str, limit: int = 50) -> list[RiskEventRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT account_id, ts, kind, message FROM risk_events "
                "WHERE account_id = ? ORDER BY id DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [RiskEventRecord(r[0], datetime.fromisoformat(r[1]), r[2], r[3]) for r in rows]

    def recent_events_all(self, limit: int = 50) -> list[RiskEventRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT account_id, ts, kind, message FROM risk_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RiskEventRecord(r[0], datetime.fromisoformat(r[1]), r[2], r[3]) for r in rows]

    # --------------------------------------------------------------- trades
    def record_trade_open(self, trade: TradeRecord) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO trades ({_TRADE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
                    (trade.account_id, trade.trade_id, trade.symbol, trade.direction,
                     trade.entry_price, trade.stop_price, trade.take_profit, trade.quantity,
                     trade.risk, trade.opened_at.isoformat()),
                )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot journal trade {trade.trade_id}: {exc}") from exc

    def record_trade_close(
        self,
        account_id: str,
        trade_id: str,
        *,
        symbol: str | None,
        exit_price: float | None,
        realized_pnl: float,
        reason: str,
        closed_at: datetime,
    ) -> None:
        """Close a journaled trade; a trade never journaled as open is inserted."""
        with self._lock:
            try:
                cur = self._conn.execute(
                    "UPDATE trades SET exit_price = ?, realized_pnl = ?, exit_reason = ?, "
                    "closed_at = ? WHERE account_id = ? AND trade_id = ?",
                    (exit_price, realized_pnl, reason, closed_at.isoformat(), account_id, trade_id),
                )
                if cur.rowcount == 0:
                    self._conn.execute(
                        f"INSERT INTO trades ({_TRADE_COLUMNS}) "
                        "VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, ?, ?, ?, ?, ?)",
                        (account_id, trade_id, symbol or "?", closed_at.isoformat(),
                         exit_price, realized_pnl, reason, closed_at.isoformat()),
                    )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot journal close of {trade_id}: {exc}") from exc

    def recent_trades(self, limit: int = 100, account_id: str | None = None) -> list[TradeRecord]:
        """Newest first, by close time for closed trades and open time otherwise."""
        sql = f"SELECT {_TRADE_COLUMNS} FROM trades"
        params: list[Any] = []
        if account_id is not None:
            sql += " WHERE account_id = ?"
            params.append(account_id)
        sql += " ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_trade(r) for r in rows]

    # ------------------------------------------------------ control requests
    def enqueue_control(self, account_id: str, action: str, argument: str, operator: str) -> int:
        """Queue an operator action for the process that owns the engines."""
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO control_requests (account_id, action, argument, operator, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (account_id, action, argument, operator, utc_now().isoformat()),
                )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot queue control request: {exc}") from exc
            return int(cur.lastrowid or 0)

    def claim_controls(self) -> list[ControlRequest]:
        """Atomically take every unclaimed request; each is returned exactly once."""
        now = utc_now().isoformat()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    rows = self._conn.execute(
                        f"SELECT {_CONTROL_COLUMNS} FROM control_requests "
                        "WHERE claimed_at IS NULL ORDER BY id"
                    ).fetchall()
                    self._conn.execute(
                        "UPDATE control_requests SET claimed_at = ? WHERE claimed_at IS NULL", (now,)
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot claim control requests: {exc}") from exc
        return [_control(r) for r in rows]

    def complete_control(self, request_id: int, ok: bool, result: str) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE control_requests SET completed_at = ?, ok = ?, result = ? WHERE id = ?",
                    (utc_now().isoformat(), int(ok), result, request_id),
                )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot complete control request: {exc}") from exc

    def get_control(self, request_id: int) -> ControlRequest | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_CONTROL_COLUMNS} FROM control_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return None if row is None else _control(row)

    # ------------------------------------------------------------ key/value
    def get_value(self, key: str) -> str | None:
        """Small service bookmarks (e.g. the Telegram update offset)."""
        with self._lock:
            try:
                row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot read {key}: {exc}") from exc
        return None if row is None else str(row[0])

    def set_value(self, key: str, value: str) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) "
                    "DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, value, utc_now().isoformat()),
                )
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot save {key}: {exc}") from exc

    # ------------------------------------------------------------ lifecycle
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
