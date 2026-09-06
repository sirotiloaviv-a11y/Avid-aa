"""The AI provider seam (44).

Nothing above this module knows which vendor answers. A provider receives a
fully-built prompt plus the candidate content the rules engine already
approved, and returns text. It never gets a database handle, and it never gets
to widen the candidate set.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIMessage:
    role: str          # "user" | "assistant"
    content: str


@dataclass
class AIRequest:
    system: str
    messages: list[AIMessage]
    context_blocks: list[str] = field(default_factory=list)
    max_tokens: int = 600
    temperature: float = 0.4
    metadata: dict[str, Any] = field(default_factory=dict)

    def prompt_text(self) -> str:
        parts = [self.system]
        if self.context_blocks:
            parts.append("\n\n".join(self.context_blocks))
        for message in self.messages:
            parts.append(f"{message.role}: {message.content}")
        return "\n\n".join(parts)


@dataclass
class AIResponse:
    text: str
    provider: str
    tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"        # ok | blocked | error
    error: str = ""


class AIProvider(ABC):
    """Contract every provider implements."""

    name = "abstract"

    @abstractmethod
    def complete(self, request: AIRequest) -> AIResponse:  # pragma: no cover - interface
        ...

    @property
    def is_mock(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "mock": self.is_mock, "ready": True}


class ProviderError(RuntimeError):
    pass


def timed(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
