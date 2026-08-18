"""Runtime state the dashboard reads: alert history and per-source health.

The monitors and the notifier write here; ``dashboard.py`` only reads. Alert
history is persisted so a redeploy does not wipe the visible record — it is a
bounded ring buffer, not a database.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alerts import Alert
from .keywords import Severity

log = logging.getLogger(__name__)

DEFAULT_HISTORY = 100


@dataclass
class AlertRecord:
    """A flattened, JSON-serialisable snapshot of a delivered alert."""

    timestamp: float
    severity: str
    severity_value: int
    source: str
    source_kind: str
    title: str
    phrases: list[str]
    url: str | None = None
    delivered: bool = True

    @classmethod
    def from_alert(cls, alert: Alert, delivered: bool = True) -> "AlertRecord":
        return cls(
            timestamp=alert.detected_at.timestamp(),
            severity=alert.severity.name,
            severity_value=int(alert.severity),
            source=alert.source,
            source_kind=alert.source_kind,
            title=alert.title[:200],
            phrases=alert.phrases,
            url=alert.url,
            delivered=delivered,
        )

    @property
    def when(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)


@dataclass
class SourceHealth:
    """Rolling health for one feed or channel."""

    name: str
    kind: str                     # "rss" | "telegram"
    last_success: float | None = None
    last_error: float | None = None
    last_error_message: str = ""
    consecutive_errors: int = 0
    poll_count: int = 0
    items_seen: int = 0
    alerts_raised: int = 0

    @property
    def status(self) -> str:
        if self.consecutive_errors >= 3:
            return "down"
        if self.consecutive_errors > 0:
            return "degraded"
        if self.last_success is None:
            return "pending"
        return "ok"

    def record_success(self, items: int = 0) -> None:
        self.last_success = time.time()
        self.consecutive_errors = 0
        self.poll_count += 1
        self.items_seen += items

    def record_error(self, message: str) -> None:
        self.last_error = time.time()
        self.last_error_message = str(message)[:300]
        self.consecutive_errors += 1
        self.poll_count += 1


class Runtime:
    """Shared, in-process state. Single-threaded asyncio — no locking needed."""

    def __init__(self, history_size: int = DEFAULT_HISTORY, path: Path | None = None):
        self.started_at = time.time()
        self.history_size = history_size
        self.path = path
        self.alerts: deque[AlertRecord] = deque(maxlen=history_size)
        self.sources: dict[str, SourceHealth] = {}
        self.alerts_sent = 0
        self.alerts_failed = 0
        self.last_alert_at: float | None = None
        self._load()

    # ------------------------------------------------------------ sources
    def register_source(self, name: str, kind: str) -> SourceHealth:
        health = self.sources.get(name)
        if health is None:
            health = SourceHealth(name=name, kind=kind)
            self.sources[name] = health
        return health

    def source(self, name: str, kind: str = "rss") -> SourceHealth:
        return self.register_source(name, kind)

    def rename_source(self, old: str, new: str) -> None:
        """A feed is first registered by URL, then re-keyed to its real title
        once the first successful poll reveals it — so the dashboard and the
        alert records agree on one name."""
        if old == new or old not in self.sources:
            return
        health = self.sources.pop(old)
        health.name = new
        existing = self.sources.get(new)
        if existing is not None:
            # Merge counters rather than losing the older entry.
            health.items_seen += existing.items_seen
            health.alerts_raised += existing.alerts_raised
            health.poll_count += existing.poll_count
        self.sources[new] = health

    # ------------------------------------------------------------- alerts
    def record_alert(self, alert: Alert, delivered: bool) -> None:
        self.alerts.appendleft(AlertRecord.from_alert(alert, delivered))
        self.last_alert_at = time.time()
        if delivered:
            self.alerts_sent += 1
        else:
            self.alerts_failed += 1
        health = self.sources.get(alert.source)
        if health is not None:
            health.alerts_raised += 1
        self.save()

    # -------------------------------------------------------------- views
    def snapshot(self) -> dict[str, Any]:
        """Everything the dashboard needs, as plain JSON-safe data."""
        now = time.time()
        by_severity: dict[str, int] = {s.name: 0 for s in Severity}
        for record in self.alerts:
            by_severity[record.severity] = by_severity.get(record.severity, 0) + 1

        return {
            "generated_at": now,
            "started_at": self.started_at,
            "uptime_seconds": int(now - self.started_at),
            "alerts_sent": self.alerts_sent,
            "alerts_failed": self.alerts_failed,
            "last_alert_at": self.last_alert_at,
            "history_size": self.history_size,
            "by_severity": by_severity,
            "sources": [
                {**asdict(health), "status": health.status}
                for health in sorted(self.sources.values(), key=lambda h: (h.kind, h.name))
            ],
            "alerts": [asdict(record) for record in self.alerts],
        }

    # ------------------------------------------------------------ persist
    def _load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read alert history %s: %s", self.path, exc)
            return
        for entry in data.get("alerts", [])[: self.history_size]:
            try:
                self.alerts.append(AlertRecord(**entry))
            except TypeError:
                continue
        self.alerts_sent = int(data.get("alerts_sent", 0) or 0)
        self.alerts_failed = int(data.get("alerts_failed", 0) or 0)
        self.last_alert_at = data.get("last_alert_at")
        log.info("Loaded %d historical alerts.", len(self.alerts))

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alerts": [asdict(r) for r in self.alerts],
            "alerts_sent": self.alerts_sent,
            "alerts_failed": self.alerts_failed,
            "last_alert_at": self.last_alert_at,
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("Could not persist alert history: %s", exc)
            Path(tmp).unlink(missing_ok=True)
