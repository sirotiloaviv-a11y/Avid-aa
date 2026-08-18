"""Durable state: which items were already alerted, and the Telegram offset.

The container this runs in is disposable, so the state file must live on a
mounted volume if you want dedupe to survive a restart. Without persistence the
worst case is a small burst of repeat alerts after a redeploy, which
``prime_without_alerting`` is designed to prevent.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path, max_entries: int = 5000):
        self.path = Path(path)
        self.max_entries = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._telegram_offset: int = 0
        self._dirty = False
        self._load()

    # ----------------------------------------------------------------- io
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read state file %s (%s); starting fresh.", self.path, exc)
            return
        seen = data.get("seen", {})
        if isinstance(seen, dict):
            self._seen = OrderedDict(
                (str(k), float(v)) for k, v in seen.items() if isinstance(v, (int, float))
            )
        self._telegram_offset = int(data.get("telegram_offset", 0) or 0)
        log.info("Loaded state: %d seen items, telegram offset %d.",
                 len(self._seen), self._telegram_offset)

    def save(self, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seen": dict(self._seen),
            "telegram_offset": self._telegram_offset,
            "saved_at": time.time(),
        }
        # Atomic replace so a crash mid-write cannot corrupt the file.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError as exc:
            log.warning("Could not persist state to %s: %s", self.path, exc)
            Path(tmp).unlink(missing_ok=True)

    # -------------------------------------------------------------- dedupe
    def is_new(self, key: str) -> bool:
        return key not in self._seen

    def mark_seen(self, key: str) -> None:
        self._seen[key] = time.time()
        self._seen.move_to_end(key)
        self._dirty = True
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)

    def seen_at(self, key: str) -> float | None:
        return self._seen.get(key)

    @property
    def is_empty(self) -> bool:
        return not self._seen

    # ------------------------------------------------------------ telegram
    @property
    def telegram_offset(self) -> int:
        return self._telegram_offset

    @telegram_offset.setter
    def telegram_offset(self, value: int) -> None:
        if value > self._telegram_offset:
            self._telegram_offset = value
            self._dirty = True
