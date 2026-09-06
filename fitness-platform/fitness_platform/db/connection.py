"""SQLite connection handling.

One connection per thread (sqlite3 objects are not shareable across threads),
row factory set to ``sqlite3.Row`` so repositories can return mappings, and
foreign keys enforced — SQLite leaves them off by default, which silently turns
every ``REFERENCES`` clause in the schema into a comment.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from ..config import get_settings

_local = threading.local()
_bootstrapped: set[str] = set()
_bootstrap_lock = threading.Lock()

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _database_path() -> str:
    return get_settings().database_path


def _configure(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_connection() -> sqlite3.Connection:
    path = _database_path()
    existing: sqlite3.Connection | None = getattr(_local, "connection", None)
    if existing is not None and getattr(_local, "path", None) == path:
        return existing
    if existing is not None:
        existing.close()

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = _configure(sqlite3.connect(path, check_same_thread=False))
    _local.connection = connection
    _local.path = path
    _ensure_schema(connection, path)
    return connection


def _ensure_schema(connection: sqlite3.Connection, path: str) -> None:
    with _bootstrap_lock:
        if path in _bootstrapped and path != ":memory:":
            return
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
        _bootstrapped.add(path)


def reset_connection() -> None:
    """Close this thread's connection. Tests use it between cases."""
    connection: sqlite3.Connection | None = getattr(_local, "connection", None)
    if connection is not None:
        connection.close()
    _local.connection = None
    _local.path = None
    _bootstrapped.clear()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def query(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
    return list(get_connection().execute(sql, params))


def query_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
    cursor = get_connection().execute(sql, params)
    return cursor.fetchone()


def scalar(sql: str, params: Sequence[Any] | dict[str, Any] = (), default: Any = 0) -> Any:
    row = query_one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
    """Run a write and return the last row id (or the row count for updates)."""
    with transaction() as connection:
        cursor = connection.execute(sql, params)
        return cursor.lastrowid if cursor.lastrowid else cursor.rowcount


def execute_many(sql: str, rows: Sequence[Sequence[Any]]) -> None:
    with transaction() as connection:
        connection.executemany(sql, rows)
