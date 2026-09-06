"""File storage seam (50).

Video and image files do not belong in the database or in the repository. The
app writes through this interface, so moving to S3/GCS later is one new class
and an environment variable — no route or template changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class StoredFile:
    key: str
    url: str
    size: int
    content_type: str


class StorageProvider(ABC):
    name = "abstract"

    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str) -> StoredFile:
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        ...

    @abstractmethod
    def url_for(self, key: str) -> str:
        ...

    def health(self) -> dict:
        return {"provider": self.name}
