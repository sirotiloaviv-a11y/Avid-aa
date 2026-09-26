"""The server-side text-model interface every adapter implements.

Adapters turn a list of turns into a stream of events. They must:
  * stop promptly when ``cancel`` is set or ``deadline`` (time.monotonic) passes,
  * raise ProviderError with a user-safe message for every failure,
  * never log or return credentials or conversation content.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterator, Literal, Protocol, Union

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Turn:
    role: Role
    content: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Heartbeat:
    """Upstream is alive but produced no visible text (e.g. the model is thinking)."""


@dataclass(frozen=True)
class ResponseStart:
    """The provider accepted the request. ``model`` is the ID it reports serving."""

    model: str | None = None
    input_tokens: int | None = None


@dataclass(frozen=True)
class StreamEnd:
    # end_turn | stop_sequence | max_tokens | refusal | cancelled | ...
    stop_reason: str
    output_tokens: int | None = None


StreamEvent = Union[ResponseStart, TextDelta, Heartbeat, StreamEnd]

ErrorKind = Literal[
    "auth",
    "permission",
    "billing",
    "not_found",
    "bad_request",
    "too_large",
    "rate_limit",
    "overloaded",
    "server",
    "network",
    "timeout",
    "protocol",
]

# Kinds where the request was rejected before any generation, so repeating it
# cannot double-bill. Timeouts are excluded: the provider may have processed
# (and billed) a request whose response we never saw.
RETRYABLE_KINDS: frozenset[str] = frozenset({"rate_limit", "overloaded", "server"})


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


class TextProvider(Protocol):
    name: str
    model: str
    # True when output is not produced by a real model. The UI labels it.
    simulated: bool

    def stream(
        self,
        system: str,
        turns: list[Turn],
        max_tokens: int,
        cancel: threading.Event,
        deadline: float,
    ) -> Iterator[StreamEvent]: ...
