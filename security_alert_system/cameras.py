"""RTSP camera integration — PLACEHOLDER LAYER.

======================================================================
READ THIS FIRST: this script is meant to run in a cloud environment.
======================================================================

Your cameras almost certainly sit on a private LAN behind NAT
(``rtsp://192.168.1.x/...``, ``rtsp://10.0.0.x/...``). A process running in a
cloud container **cannot** reach those addresses — there is no route from the
cloud to your living room. Dropping an RTSP URL into the config below will
therefore time out, no matter how correct the URL is.

There are four ways to bridge that gap, best first:

1. **On-prem push agent (recommended).** Run a tiny script on a machine at
   home (Raspberry Pi, NAS, mini-PC). It talks to the cameras over the LAN,
   grabs a JPEG when asked, and uploads it to this service — or straight to
   your Telegram chat with the same bot token. Nothing on your home network
   is ever exposed to the internet. Implemented here as
   :class:`PushInboxConnector`, which reads snapshots the agent has dropped
   into a shared directory or object-storage mount.

2. **Private mesh VPN (Tailscale / WireGuard / ZeroTier).** Join the cloud
   container to the same overlay network as the cameras. The RTSP URLs then
   resolve normally and :class:`FFmpegConnector` works unchanged — this is the
   least-code option if you can install a VPN client in the container.

3. **Outbound reverse tunnel** (Cloudflare Tunnel, ``ssh -R``, frp). The home
   side dials out; nothing inbound is opened. Point the RTSP URL at the
   tunnel endpoint.

4. **Port-forwarding the camera to the internet — do not do this.** Consumer
   NVR/RTSP stacks are routinely exploited and most speak plaintext RTSP with
   weak credentials. If you truly must, restrict by source IP and put TLS in
   front of it.

Whatever you choose, the rest of the codebase only ever touches
:class:`CameraRegistry`, so swapping connectors is a one-line config change.

----------------------------------------------------------------------
How to wire your cameras in later
----------------------------------------------------------------------
1. Define the streams — either in ``cameras.json`` next to this file, or via
   the ``CAMERAS`` environment variable (see ``.env.example``).
2. Set ``CAMERAS_ENABLED=true`` and pick a connector with ``CAMERA_CONNECTOR``
   (``null`` | ``ffmpeg`` | ``push_inbox``).
3. Snapshots are attached automatically to any alert at or above
   ``CAMERA_SNAPSHOT_ON_SEVERITY``.

Until then the default :class:`NullConnector` is active: it logs the request
and returns nothing, so alerting works exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraStream:
    """One camera. ``rtsp_url`` may embed credentials, so never log it raw."""

    id: str
    name: str
    rtsp_url: str
    enabled: bool = True
    # "tcp" is far more reliable than "udp" across tunnels and VPNs.
    transport: str = "tcp"
    timeout_seconds: int = 12
    tags: list[str] = field(default_factory=list)

    @property
    def safe_url(self) -> str:
        """URL with any user:password stripped, safe for logs."""
        if "://" not in self.rtsp_url:
            return self.rtsp_url
        scheme, _, rest = self.rtsp_url.partition("://")
        host = rest.split("@")[-1]
        return f"{scheme}://{host}"


@dataclass
class Snapshot:
    camera_id: str
    camera_name: str
    image_bytes: bytes
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CameraConnector(ABC):
    """Strategy for turning a :class:`CameraStream` into a JPEG."""

    name = "base"

    @abstractmethod
    async def capture(self, stream: CameraStream) -> Snapshot | None:
        """Return a snapshot, or ``None`` if it could not be captured."""

    async def healthcheck(self) -> str:
        return f"{self.name}: no healthcheck implemented"


class NullConnector(CameraConnector):
    """Default. Does nothing except make the wiring visible in the logs."""

    name = "null"

    async def capture(self, stream: CameraStream) -> Snapshot | None:
        log.info(
            "[camera placeholder] would capture %s (%s) — no connector configured.",
            stream.id, stream.safe_url,
        )
        return None

    async def healthcheck(self) -> str:
        return "null: placeholder connector, cameras are not wired up yet"


class FFmpegConnector(CameraConnector):
    """Grab a single frame over RTSP using ffmpeg.

    Only works when the host running this script can actually reach the camera
    (options 2 and 3 in the module docstring). Requires ``ffmpeg`` on PATH.
    """

    name = "ffmpeg"

    def __init__(self, ffmpeg_path: str | None = None, jpeg_quality: int = 4):
        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self._quality = jpeg_quality

    async def capture(self, stream: CameraStream) -> Snapshot | None:
        args = [
            self._ffmpeg,
            "-nostdin", "-loglevel", "error",
            "-rtsp_transport", stream.transport,
            "-timeout", str(stream.timeout_seconds * 1_000_000),  # microseconds
            "-i", stream.rtsp_url,
            "-frames:v", "1",
            "-q:v", str(self._quality),
            "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("ffmpeg not found on PATH; cannot capture %s.", stream.id)
            return None

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=stream.timeout_seconds + 5
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            log.warning(
                "Timed out capturing %s (%s). In a cloud container this usually "
                "means the camera is on an unreachable private network.",
                stream.id, stream.safe_url,
            )
            return None

        if process.returncode != 0 or not stdout:
            log.warning(
                "ffmpeg failed for %s (%s): %s",
                stream.id, stream.safe_url, stderr.decode("utf-8", "replace").strip()[:300],
            )
            return None

        return Snapshot(stream.id, stream.name, stdout)

    async def healthcheck(self) -> str:
        found = shutil.which(self._ffmpeg) or Path(self._ffmpeg).is_file()
        return f"ffmpeg: {'available' if found else 'NOT FOUND on PATH'}"


class PushInboxConnector(CameraConnector):
    """Read snapshots that an on-prem agent uploads into a shared directory.

    The cloud side never dials the camera; it just picks up the newest
    ``<camera_id>*.jpg`` written into ``inbox_dir`` (a mounted volume, an S3/GCS
    fuse mount, or a directory your agent POSTs into). Snapshots older than
    ``max_age_seconds`` are ignored so a stale image is never passed off as a
    live one.

    Sketch of the matching home-side agent::

        # runs at home, on the same LAN as the cameras
        while True:
            for cam in cameras:
                frame = ffmpeg_grab(cam.rtsp_url)          # local, fast
                upload(f"{cam.id}-{int(time.time())}.jpg", frame)
            time.sleep(5)
    """

    name = "push_inbox"

    def __init__(self, inbox_dir: Path | str, max_age_seconds: int = 120):
        self._inbox = Path(inbox_dir)
        self._max_age = max_age_seconds

    async def capture(self, stream: CameraStream) -> Snapshot | None:
        return await asyncio.to_thread(self._latest_for, stream)

    def _latest_for(self, stream: CameraStream) -> Snapshot | None:
        if not self._inbox.is_dir():
            log.warning("Snapshot inbox %s does not exist.", self._inbox)
            return None
        candidates = sorted(
            self._inbox.glob(f"{stream.id}*.jpg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            log.info("No pushed snapshot found for camera %s.", stream.id)
            return None

        newest = candidates[0]
        age = datetime.now(timezone.utc).timestamp() - newest.stat().st_mtime
        if age > self._max_age:
            log.warning("Newest snapshot for %s is %.0fs old; skipping.", stream.id, age)
            return None
        return Snapshot(stream.id, stream.name, newest.read_bytes())

    async def healthcheck(self) -> str:
        return f"push_inbox: {self._inbox} {'exists' if self._inbox.is_dir() else 'MISSING'}"


class CameraRegistry:
    """Holds the configured streams and the active connector."""

    def __init__(
        self,
        streams: list[CameraStream] | None = None,
        connector: CameraConnector | None = None,
        enabled: bool = False,
    ):
        self.streams = streams or []
        self.connector = connector or NullConnector()
        self.enabled = enabled

    async def capture_all(self, tag: str | None = None) -> list[Snapshot]:
        """Capture every enabled camera (optionally filtered by tag), in parallel."""
        if not self.enabled:
            return []
        targets = [
            s for s in self.streams
            if s.enabled and (tag is None or tag in s.tags)
        ]
        if not targets:
            return []

        results = await asyncio.gather(
            *(self.connector.capture(s) for s in targets), return_exceptions=True
        )
        snapshots: list[Snapshot] = []
        for stream, result in zip(targets, results):
            if isinstance(result, BaseException):
                log.warning("Capture raised for %s: %s", stream.id, result)
            elif result is not None:
                snapshots.append(result)
        return snapshots

    def describe(self) -> str:
        if not self.enabled:
            return "cameras: disabled (placeholder only)"
        names = ", ".join(s.id for s in self.streams if s.enabled) or "none"
        return f"cameras: {self.connector.name} connector, streams: {names}"

    # ---------------------------------------------------------------- config
    @classmethod
    def from_env(cls, base_dir: Path) -> "CameraRegistry":
        """Build from ``CAMERAS`` / ``cameras.json`` + ``CAMERA_*`` env vars."""
        enabled = (os.getenv("CAMERAS_ENABLED", "false").lower()
                   in {"1", "true", "yes", "on"})

        raw = os.getenv("CAMERAS", "").strip()
        entries: list[dict] = []
        if raw:
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError:
                log.error("CAMERAS is not valid JSON; ignoring it.")
        else:
            config_file = base_dir / "cameras.json"
            if config_file.is_file():
                try:
                    entries = json.loads(config_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    log.error("cameras.json is not valid JSON; ignoring it.")

        streams = [
            CameraStream(
                id=str(entry.get("id") or f"cam{index + 1}"),
                name=str(entry.get("name") or entry.get("id") or f"Camera {index + 1}"),
                rtsp_url=str(entry.get("rtsp_url", "")),
                enabled=bool(entry.get("enabled", True)),
                transport=str(entry.get("transport", "tcp")),
                timeout_seconds=int(entry.get("timeout_seconds", 12)),
                tags=list(entry.get("tags", [])),
            )
            for index, entry in enumerate(entries)
            if isinstance(entry, dict)
        ]

        kind = os.getenv("CAMERA_CONNECTOR", "null").strip().lower()
        connector: CameraConnector
        if kind == "ffmpeg":
            connector = FFmpegConnector(os.getenv("FFMPEG_PATH") or None)
        elif kind == "push_inbox":
            connector = PushInboxConnector(
                os.getenv("CAMERA_INBOX_DIR", str(base_dir / "state" / "snapshots")),
                int(os.getenv("CAMERA_SNAPSHOT_MAX_AGE", "120")),
            )
        else:
            connector = NullConnector()

        return cls(streams=streams, connector=connector, enabled=enabled)
