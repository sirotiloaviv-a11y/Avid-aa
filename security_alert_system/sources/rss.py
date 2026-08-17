"""Polls news RSS feeds and raises alerts on keyword hits."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import httpx

from ..alerts import Alert
from ..config import Config
from ..notifier import Notifier
from ..state import StateStore

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
USER_AGENT = "SecurityAlertBot/1.0 (+RSS monitor; contact: configure in .env)"


def strip_html(raw: str) -> str:
    """RSS descriptions are HTML fragments; keywords must match the text."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>|</p>", "\n", raw, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    return html.unescape(text).strip()


class RSSMonitor:
    """One instance polls every configured feed on a fixed interval."""

    def __init__(self, config: Config, notifier: Notifier, state: StateStore):
        self._config = config
        self._notifier = notifier
        self._state = state
        # Conditional-GET bookkeeping per feed, so we re-download only on change.
        self._etags: dict[str, str] = {}
        self._modified: dict[str, str] = {}
        self._feed_titles: dict[str, str] = {}

    async def run(self, stop: asyncio.Event) -> None:
        if not self._config.rss_feeds:
            log.info("No RSS feeds configured; RSS monitor idle.")
            return

        priming = self._config.prime_without_alerting and self._state.is_empty
        if priming:
            log.info("First run: indexing current feed contents without alerting.")

        async with httpx.AsyncClient(
            timeout=self._config.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            while not stop.is_set():
                started = time.monotonic()
                try:
                    await self._poll_once(client, alerting=not priming)
                except Exception:  # noqa: BLE001 - one bad cycle must not kill the loop
                    log.exception("RSS poll cycle failed; continuing.")
                priming = False
                self._state.save()

                elapsed = time.monotonic() - started
                delay = max(5.0, self._config.rss_poll_seconds - elapsed)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        log.info("RSS monitor stopped.")

    async def _poll_once(self, client: httpx.AsyncClient, alerting: bool) -> None:
        results = await asyncio.gather(
            *(self._poll_feed(client, url, alerting) for url in self._config.rss_feeds),
            return_exceptions=True,
        )
        for url, result in zip(self._config.rss_feeds, results):
            if isinstance(result, BaseException):
                log.warning("Feed %s failed: %s", url, result)

    async def _poll_feed(self, client: httpx.AsyncClient, url: str, alerting: bool) -> None:
        headers: dict[str, str] = {}
        if etag := self._etags.get(url):
            headers["If-None-Match"] = etag
        if modified := self._modified.get(url):
            headers["If-Modified-Since"] = modified

        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("Could not fetch %s: %s", url, exc)
            return

        if response.status_code == 304:
            log.debug("Feed unchanged: %s", url)
            return
        if response.status_code >= 400:
            log.warning("Feed %s returned HTTP %d.", url, response.status_code)
            return

        if tag := response.headers.get("ETag"):
            self._etags[url] = tag
        if last_mod := response.headers.get("Last-Modified"):
            self._modified[url] = last_mod

        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        if parsed.bozo and not parsed.entries:
            log.warning("Could not parse feed %s: %s", url, parsed.get("bozo_exception"))
            return

        feed_title = (parsed.feed.get("title") or url).strip()
        self._feed_titles[url] = feed_title

        for entry in parsed.entries[: self._config.max_items_per_feed]:
            await self._handle_entry(url, feed_title, entry, alerting)

    async def _handle_entry(self, feed_url: str, feed_title: str, entry, alerting: bool) -> None:
        key = self._dedupe_key(feed_url, entry)
        if not self._state.is_new(key):
            return
        self._state.mark_seen(key)

        title = strip_html(entry.get("title", ""))
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        content = ""
        if blocks := entry.get("content"):
            content = strip_html(" ".join(b.get("value", "") for b in blocks))

        matches = self._config.matcher.find_all(title, summary, content)
        if not matches:
            return
        if not alerting:
            log.debug("Priming: skipped alert for %s", title[:60])
            return

        alert = Alert(
            source=feed_title,
            source_kind="rss",
            title=title,
            body=summary or content,
            matches=matches,
            url=entry.get("link"),
            published_at=_entry_datetime(entry),
            dedupe_key=key,
        )
        await self._notifier.send_alert(alert)

    @staticmethod
    def _dedupe_key(feed_url: str, entry) -> str:
        identity = (
            entry.get("id")
            or entry.get("guid")
            or entry.get("link")
            or entry.get("title", "")
        )
        digest = hashlib.sha1(f"{feed_url}|{identity}".encode("utf-8")).hexdigest()
        return f"rss:{digest[:20]}"


def _entry_datetime(entry) -> datetime | None:
    for field_name in ("published_parsed", "updated_parsed"):
        value = entry.get(field_name)
        if value:
            try:
                return datetime.fromtimestamp(time.mktime(value), tz=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None
