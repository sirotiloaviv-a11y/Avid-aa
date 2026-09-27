"""An exclusive, crash-safe lock marking "the trading bot is running".

The bot process holds it for its whole life. Operator tools (the CLI) probe
it: if it is held, they must not write account state themselves, because the
running bot would overwrite it from memory on its next save. They queue a
control request instead, which the bot applies.

The OS releases the lock when the process dies, even on ``kill -9``, so a
crash never leaves a stale lock behind (unlike a PID file).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: IO[str] | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> bool:
        """Try to take the lock without blocking. Returns whether it was taken."""
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115
        try:
            _lock(handle)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> ProcessLock:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


if sys.platform == "win32":  # pragma: no cover - the VPS target is Linux
    import msvcrt

    def _lock(handle: IO[str]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: IO[str]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
