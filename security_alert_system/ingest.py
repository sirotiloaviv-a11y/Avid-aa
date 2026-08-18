"""One authenticated pipe any outside source can push into.

RSS and Telegram are pulled by this process. Everything else — WhatsApp, a
scraper for a site with no feed, a camera agent at home, a script on your
phone — lives outside it and pushes in here:

    POST /ingest
    Authorization: Bearer <INGEST_TOKEN>
    {"source": "וואטסאפ · שכונה", "text": "...", "url": "...", "kind": "whatsapp"}

Everything that arrives runs the same keyword matcher, the same dedupe, the
same severity ladder, and lands as the same alert with the same assistant
context and the same dashboard row. A new source is a new bridge script, not a
new branch inside the monitor.

WHY A SEPARATE PROCESS, NOT A PLUGIN
------------------------------------
The bridges are the fragile and risky parts. A WhatsApp reader can get the
account banned; a scraper breaks when a site changes its markup; a camera
agent sits on a home network that reboots. Keeping them out of process means
any of them can crash, be killed, or be rewritten without touching the thing
that has to keep running — and the monitor keeps alerting from its own sources
while a bridge is down.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .alerts import Alert
from .config import Config
from .monitoring import Runtime
from .notifier import Notifier
from .state import StateStore

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000
# A bridge that goes into a loop must not be able to spend the whole alert
# budget. Counted per source, over a rolling window.
RATE_LIMIT_PER_MINUTE = 60


@dataclass
class IngestResult:
    accepted: bool
    matched: bool
    alerted: bool
    severity: str | None = None
    phrases: list[str] | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "matched": self.matched,
            "alerted": self.alerted,
            "severity": self.severity,
            "phrases": self.phrases or [],
            "reason": self.reason,
        }


class IngestPipeline:
    """Takes an outside message and runs it through the normal alert path."""

    def __init__(
        self,
        config: Config,
        notifier: Notifier,
        state: StateStore,
        runtime: Runtime | None = None,
    ):
        self._config = config
        self._notifier = notifier
        self._state = state
        self._runtime = runtime
        self._recent: dict[str, list[float]] = {}

    def _rate_limited(self, source: str) -> bool:
        now = time.time()
        window = [t for t in self._recent.get(source, []) if now - t < 60]
        self._recent[source] = window
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            return True
        window.append(now)
        return False

    async def submit(
        self,
        source: str,
        text: str,
        url: str | None = None,
        kind: str = "external",
        external_id: str | None = None,
        timestamp: float | None = None,
    ) -> IngestResult:
        source = (source or "").strip()[:120]
        text = (text or "").strip()[:MAX_TEXT_CHARS]

        if not source:
            return IngestResult(False, False, False, reason="source is required")
        if not text:
            return IngestResult(False, False, False, reason="text is required")
        if self._rate_limited(source):
            log.warning("Ingest rate limit hit for source %s.", source)
            return IngestResult(False, False, False, reason="rate limited")

        health = self._runtime.source(source, kind) if self._runtime else None
        if health:
            health.record_success(items=1)

        # The bridge's own id when it has one (a WhatsApp message id, a page
        # URL); otherwise the content itself. Either way the same message
        # pushed twice — a bridge restart replaying its backlog — alerts once.
        identity = external_id or url or text
        key = "ingest:" + hashlib.sha1(
            f"{source}|{identity}".encode("utf-8")
        ).hexdigest()[:20]
        if not self._state.is_new(key):
            return IngestResult(True, False, False, reason="already seen")
        self._state.mark_seen(key)

        matches = self._config.matcher.find_all(text)
        if not matches:
            return IngestResult(True, False, False, reason="no keyword matched")

        published = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None
        )
        alert = Alert(
            source=source,
            source_kind=kind,
            title=text.splitlines()[0][:200] if text else source,
            body=text,
            matches=matches,
            url=url,
            published_at=published,
            dedupe_key=key,
        )
        # Do NOT bump health.alerts_raised here — Runtime.record_alert already
        # does it for every source when the notifier delivers, and counting in
        # both places double-reports every external alert on the dashboard.
        alerted = await self._notifier.send_alert(alert)
        self._state.save()

        return IngestResult(
            accepted=True,
            matched=True,
            alerted=alerted,
            severity=alert.severity.name,
            phrases=alert.phrases,
        )
