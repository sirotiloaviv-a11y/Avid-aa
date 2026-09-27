"""Economic-calendar safeguard: no new entries around high-impact releases.

By default the calendar comes from the public ForexFactory weekly JSON feed
and is cached on disk, so a restart or a feed outage does not leave the bot
blind. A local JSON file can be used instead (or as well) for a
hand-maintained list: FOMC dates, for example, are published a year ahead.

When no calendar data is fresh enough to trust, the guard **fails closed**
(blocks entries) unless ``NEWS_FAIL_CLOSED=false``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence, cast

from ..config import NewsConfig, NewsSource
from ..utils.logger import get_logger
from ..utils.time_utils import ensure_utc, utc_now

log = get_logger(__name__)


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HOLIDAY = "holiday"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> Impact:
        value = (raw or "").strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.UNKNOWN


@dataclass(frozen=True)
class EconomicEvent:
    title: str
    currency: str
    time: datetime  # UTC
    impact: Impact


class CalendarUnavailable(RuntimeError):
    """The calendar provider could not produce any usable data."""


class CalendarProvider(Protocol):
    def fetch(self) -> list[EconomicEvent]: ...


def parse_events(raw: Any) -> list[EconomicEvent]:
    """Parse ForexFactory-style JSON: ``[{title, country, date, impact}, ...]``.

    Malformed entries are skipped individually; a non-list payload raises.
    """
    if not isinstance(raw, list):
        raise CalendarUnavailable("calendar payload is not a JSON list")
    events: list[EconomicEvent] = []
    for entry in cast("list[object]", raw):
        if not isinstance(entry, dict):
            continue
        item = cast("dict[str, Any]", entry)
        try:
            when = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
            events.append(
                EconomicEvent(
                    title=str(item.get("title", "")).strip(),
                    currency=str(item.get("country") or item.get("currency") or "").upper(),
                    time=ensure_utc(when),
                    impact=Impact.parse(str(item.get("impact", ""))),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("Skipping calendar entry %r: %s", item, exc)
    return events


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class JsonFileCalendarProvider:
    """Events from a local JSON file in the same shape as the ForexFactory feed."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self) -> list[EconomicEvent]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalendarUnavailable(f"cannot read calendar file {self.path}: {exc}") from exc
        return parse_events(raw)


class HttpCalendarProvider:
    """Fetches the ForexFactory weekly JSON feed, mirroring it to a cache file.

    On a failed fetch it falls back to the cache, so the week's events are
    still known after a restart during a feed outage.
    """

    def __init__(
        self,
        url: str,
        cache_file: Path,
        *,
        timeout: float = 15.0,
        max_cache_age: timedelta = timedelta(hours=24),
        opener: Callable[[str, float], bytes] | None = None,
    ) -> None:
        self.url = url
        self.cache_file = cache_file
        self.timeout = timeout
        self.max_cache_age = max_cache_age
        self._open = opener or self._http_get

    @staticmethod
    def _http_get(url: str, timeout: float) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "trading-bot/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data: bytes = response.read()
            return data

    def fetch(self) -> list[EconomicEvent]:
        try:
            body = self._open(self.url, self.timeout)
            events = parse_events(json.loads(body))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError,
                CalendarUnavailable) as exc:
            log.warning("Calendar fetch from %s failed (%s); trying cache", self.url, exc)
            return self._read_cache()
        try:
            _atomic_write(self.cache_file, body.decode("utf-8"))
        except OSError as exc:
            log.warning("Could not write calendar cache %s: %s", self.cache_file, exc)
        return events

    def _read_cache(self) -> list[EconomicEvent]:
        if not self.cache_file.is_file():
            raise CalendarUnavailable("calendar feed unreachable and no cache on disk")
        # A week-old cache holds last week's events: trusting it would mean no blackouts.
        age = utc_now() - datetime.fromtimestamp(self.cache_file.stat().st_mtime, timezone.utc)
        if age > self.max_cache_age:
            raise CalendarUnavailable(f"calendar feed unreachable and cache is {age} old")
        return JsonFileCalendarProvider(self.cache_file).fetch()


class CompositeCalendarProvider:
    """Merges several providers; succeeds if at least one does."""

    def __init__(self, providers: Sequence[CalendarProvider]) -> None:
        self.providers = list(providers)

    def fetch(self) -> list[EconomicEvent]:
        events: list[EconomicEvent] = []
        errors: list[str] = []
        for provider in self.providers:
            try:
                events.extend(provider.fetch())
            except CalendarUnavailable as exc:
                errors.append(str(exc))
        if errors and len(errors) == len(self.providers):
            raise CalendarUnavailable("; ".join(errors))
        for err in errors:
            log.warning("Calendar provider failed: %s", err)
        return events


@dataclass(frozen=True)
class NewsCheck:
    allowed: bool
    reason: str | None = None
    event: EconomicEvent | None = None


class NewsGuard:
    """Answers "may a new position be opened at time *t*?" from the calendar."""

    def __init__(
        self,
        provider: CalendarProvider | None,
        config: NewsConfig,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.provider = provider
        self.config = config
        self._clock = clock
        self._events: list[EconomicEvent] = []
        self._loaded_at: datetime | None = None
        self._last_attempt: datetime | None = None
        self._lock = threading.Lock()
        self._keywords = tuple(k.lower() for k in config.keywords)
        self._currencies = frozenset(c.upper() for c in config.currencies)

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def is_high_impact(self, event: EconomicEvent) -> bool:
        if self._currencies and event.currency not in self._currencies:
            return False
        if event.impact is Impact.HIGH:
            return True
        title = event.title.lower()
        return any(k in title for k in self._keywords)

    def refresh(self, *, force: bool = False) -> None:
        """Reload the calendar if the refresh interval has elapsed."""
        if self.provider is None:
            return
        now = self._clock()
        with self._lock:
            if not force and self._last_attempt is not None:
                succeeded = self._loaded_at is not None and self._loaded_at >= self._last_attempt
                # Retry a failed load sooner than a full interval, but not every call.
                wait = timedelta(minutes=self.config.refresh_minutes if succeeded else 5)
                if now - self._last_attempt < wait:
                    return
            self._last_attempt = now
            try:
                events = self.provider.fetch()
            except CalendarUnavailable as exc:
                log.error("Economic calendar unavailable: %s", exc)
                return
            except Exception:  # a provider bug must not crash the risk engine
                log.exception("Economic calendar provider raised unexpectedly")
                return
            self._events = sorted(
                (e for e in events if self.is_high_impact(e)), key=lambda e: e.time
            )
            self._loaded_at = now
            log.info("Loaded %d high-impact events (of %d)", len(self._events), len(events))

    def check(self, now: datetime | None = None) -> NewsCheck:
        if self.provider is None:
            return NewsCheck(True)
        self.refresh()
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            loaded_at, events = self._loaded_at, self._events

        max_age = timedelta(hours=self.config.max_data_age_hours)
        if loaded_at is None or now - loaded_at > max_age:
            if self.config.fail_closed:
                return NewsCheck(False, "economic calendar unavailable or stale (fail-closed)")
            log.warning("Economic calendar unavailable; trading without news protection")
            return NewsCheck(True)

        before = timedelta(minutes=self.config.minutes_before)
        after = timedelta(minutes=self.config.minutes_after)
        for event in events:
            if event.time - before <= now <= event.time + after:
                when = "in" if now < event.time else "since"
                minutes = abs(int((event.time - now).total_seconds() // 60))
                return NewsCheck(
                    False,
                    f"news blackout: {event.currency} {event.title} "
                    f"({when} {minutes} min, {event.time:%H:%M} UTC)",
                    event,
                )
        return NewsCheck(True)

    def upcoming(self, now: datetime | None = None, within: timedelta = timedelta(hours=24)) -> list[EconomicEvent]:
        now = ensure_utc(now) if now is not None else self._clock()
        with self._lock:
            return [e for e in self._events if now <= e.time <= now + within]


def build_news_guard(config: NewsConfig, *, clock: Callable[[], datetime] = utc_now) -> NewsGuard:
    providers: list[CalendarProvider] = []
    if config.source is NewsSource.FOREXFACTORY:
        providers.append(
            HttpCalendarProvider(
                config.url,
                config.cache_file,
                max_cache_age=timedelta(hours=config.max_data_age_hours),
            )
        )
    if config.file is not None:
        providers.append(JsonFileCalendarProvider(config.file))
    provider: CalendarProvider | None
    if config.source is NewsSource.NONE and config.file is None:
        provider = None
    elif len(providers) == 1:
        provider = providers[0]
    else:
        provider = CompositeCalendarProvider(providers)
    return NewsGuard(provider, config, clock=clock)
