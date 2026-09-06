"""Filesystem storage for development and single-box deployments."""

from __future__ import annotations

import re
from pathlib import Path

from ...config import get_settings
from .provider import StorageProvider, StoredFile

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._/-]")
MAX_BYTES = 512 * 1024 * 1024


class LocalStorageProvider(StorageProvider):
    name = "local"

    def __init__(self) -> None:
        settings = get_settings()
        self._root = Path(settings.storage_root)
        self._prefix = settings.storage_public_prefix.rstrip("/")

    def _path(self, key: str) -> Path:
        safe = _SAFE_KEY.sub("-", key).lstrip("/")
        target = (self._root / safe).resolve()
        # Refuse anything that escapes the storage root.
        if not str(target).startswith(str(self._root.resolve())):
            raise ValueError("invalid storage key")
        return target

    def save(self, key: str, data: bytes, content_type: str) -> StoredFile:
        if len(data) > MAX_BYTES:
            raise ValueError("file too large")
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredFile(key=key, url=self.url_for(key), size=len(data), content_type=content_type)

    def delete(self, key: str) -> bool:
        target = self._path(key)
        if target.is_file():
            target.unlink()
            return True
        return False

    def url_for(self, key: str) -> str:
        return f"{self._prefix}/{_SAFE_KEY.sub('-', key).lstrip('/')}"
