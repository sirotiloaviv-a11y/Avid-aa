"""SQLite persistence for conversations and messages.

One connection per operation keeps this safe under ThreadingHTTPServer without
sharing a connection across threads. WAL mode lets reads proceed during a write.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    -- complete | streaming | cancelled | error
    status          TEXT NOT NULL,
    -- which adapter produced an assistant message, and whether it was simulated
    provider        TEXT,
    model           TEXT,
    simulated       INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    -- provider stop reason for assistant messages, e.g. end_turn, max_tokens
    stop_reason     TEXT,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_conversation
    ON messages (conversation_id, created_at);
"""

MESSAGE_STATUSES = frozenset({"complete", "streaming", "cancelled", "error"})


@dataclass
class Conversation:
    id: str
    title: str
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    provider: str | None
    model: str | None
    simulated: bool
    error: str | None
    stop_reason: str | None
    created_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # A process that died mid-stream leaves "streaming" rows behind.
            db.execute(
                "UPDATE messages SET status='error', error='Interrupted by a server restart' "
                "WHERE status='streaming'"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    # conversations -----------------------------------------------------

    def create_conversation(self, title: str) -> Conversation:
        now = _now()
        conv = Conversation(id=_new_id(), title=title, created_at=now, updated_at=now)
        with self._connect() as db:
            db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (conv.id, conv.title, conv.created_at, conv.updated_at),
            )
        return conv

    def list_conversations(self) -> list[Conversation]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [Conversation(**dict(r)) for r in rows]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        return Conversation(**dict(row)) if row else None

    def rename_conversation(
        self, conversation_id: str, title: str
    ) -> Conversation | None:
        with self._connect() as db:
            cur = db.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title, _now(), conversation_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as db:
            cur = db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            return cur.rowcount > 0

    # messages ----------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        status: str = "complete",
        provider: str | None = None,
        model: str | None = None,
        simulated: bool = False,
    ) -> Message:
        if status not in MESSAGE_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        now = _now()
        msg = Message(
            id=_new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            provider=provider,
            model=model,
            simulated=simulated,
            error=None,
            stop_reason=None,
            created_at=now,
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, status, provider,"
                " model, simulated, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    msg.id,
                    msg.conversation_id,
                    msg.role,
                    msg.content,
                    msg.status,
                    msg.provider,
                    msg.model,
                    int(msg.simulated),
                    msg.error,
                    msg.created_at,
                ),
            )
            db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now, conversation_id),
            )
        return msg

    def update_message_content(self, message_id: str, content: str) -> None:
        """Checkpoint a streaming reply so a crash keeps what was generated."""
        with self._connect() as db:
            db.execute(
                "UPDATE messages SET content=? WHERE id=?", (content, message_id)
            )

    def finish_message(
        self,
        message_id: str,
        content: str,
        status: str,
        error: str | None = None,
        stop_reason: str | None = None,
    ) -> Message | None:
        if status not in MESSAGE_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        with self._connect() as db:
            db.execute(
                "UPDATE messages SET content=?, status=?, error=?, stop_reason=? WHERE id=?",
                (content, status, error, stop_reason, message_id),
            )
            row = db.execute(
                "SELECT * FROM messages WHERE id=?", (message_id,)
            ).fetchone()
        return _message(row) if row else None

    def list_messages(self, conversation_id: str) -> list[Message]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        return [_message(r) for r in rows]


def _message(row: sqlite3.Row) -> Message:
    d = dict(row)
    d["simulated"] = bool(d["simulated"])
    return Message(**d)
