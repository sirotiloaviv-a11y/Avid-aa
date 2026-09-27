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
