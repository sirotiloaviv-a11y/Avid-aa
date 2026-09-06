"""Storage provider selection (50)."""

from __future__ import annotations

from ...config import get_settings
from .local_provider import LocalStorageProvider
from .provider import StorageProvider

_cache: dict[str, StorageProvider] = {}


def get_provider() -> StorageProvider:
    name = get_settings().storage_provider.lower()
    cached = _cache.get(name)
    if cached is not None:
        return cached
    if name != "local":
        raise RuntimeError(
            f"STORAGE_PROVIDER={name} has no implementation yet. Add a StorageProvider "
            "subclass for the object store and register it here."
        )
    provider = LocalStorageProvider()
    _cache[name] = provider
    return provider


def reset_provider_cache() -> None:
    _cache.clear()
