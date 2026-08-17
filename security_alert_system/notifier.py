"""Delivers alerts to your personal Telegram chat."""

from __future__ import annotations

import asyncio
import logging
import time

from .alerts import Alert
from .cameras import CameraRegistry
from .keywords import Severity
from .monitoring import Runtime
from .telegram_api import TelegramClient, TelegramError

log = logging.getLogger(__name__)

# Telegram tolerates roughly one message per second to a single chat.
MIN_SECONDS_BETWEEN_SENDS = 1.1


class Notifier:
    def __init__(
        self,
        client: TelegramClient,
        chat_id: str,
        cameras: CameraRegistry | None = None,
        snapshot_threshold: Severity = Severity.CRITICAL,
        runtime: Runtime | None = None,
    ):
        self._client = client
        self._chat_id = chat_id
        self._cameras = cameras
        self._snapshot_threshold = snapshot_threshold
        self._runtime = runtime
        self._lock = asyncio.Lock()
        self._last_send = 0.0

    async def _throttled_send(self, text: str) -> None:
        async with self._lock:
            gap = time.monotonic() - self._last_send
            if gap < MIN_SECONDS_BETWEEN_SENDS:
                await asyncio.sleep(MIN_SECONDS_BETWEEN_SENDS - gap)
            await self._client.send_message(self._chat_id, text)
            self._last_send = time.monotonic()

    async def send_alert(self, alert: Alert) -> bool:
        """Send one alert. Returns True if Telegram accepted it."""
        try:
            await self._throttled_send(alert.to_html())
        except TelegramError as exc:
            log.error("Failed to deliver alert from %s: %s", alert.source, exc)
            # A failed delivery is exactly what the dashboard needs to surface.
            if self._runtime:
                self._runtime.record_alert(alert, delivered=False)
            return False

        if self._runtime:
            self._runtime.record_alert(alert, delivered=True)

        log.info(
            "ALERT [%s] %s — %s | %s",
            alert.severity.name,
            alert.source,
            ", ".join(alert.phrases),
            alert.title[:80],
        )

        if self._cameras and alert.severity >= self._snapshot_threshold:
            await self._attach_camera_snapshots(alert)
        return True

    async def _attach_camera_snapshots(self, alert: Alert) -> None:
        """Best-effort: never let a camera problem swallow the text alert."""
        assert self._cameras is not None
        try:
            snapshots = await self._cameras.capture_all()
        except Exception:  # noqa: BLE001 - cameras must never break alerting
            log.exception("Camera snapshot capture failed; text alert already sent.")
            return

        for snapshot in snapshots:
            caption = f"📷 <b>{snapshot.camera_name}</b> — {alert.severity.emoji} {alert.severity.hebrew}"
            try:
                async with self._lock:
                    gap = time.monotonic() - self._last_send
                    if gap < MIN_SECONDS_BETWEEN_SENDS:
                        await asyncio.sleep(MIN_SECONDS_BETWEEN_SENDS - gap)
                    await self._client.send_photo(
                        self._chat_id, snapshot.image_bytes, caption=caption,
                        filename=f"{snapshot.camera_id}.jpg",
                    )
                    self._last_send = time.monotonic()
            except TelegramError as exc:
                log.error("Could not send snapshot from %s: %s", snapshot.camera_id, exc)

    async def send_notice(self, text: str) -> None:
        """Operational message (startup / shutdown / errors), not an alert."""
        try:
            await self._throttled_send(text)
        except TelegramError as exc:
            log.error("Could not send notice: %s", exc)
