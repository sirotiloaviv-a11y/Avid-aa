"""Conversation logic, independent of HTTP: context building and one reply's lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .providers.base import (
    Heartbeat,
    ProviderError,
    ResponseStart,
    StreamEnd,
    TextDelta,
    TextProvider,
    Turn,
)
from .store import Message, Store
from .validation import title_from_message

log = logging.getLogger("aiworkspace")

DEFAULT_TITLE = "New conversation"
SYSTEM_PROMPT = (
    "You are a helpful assistant inside a local AI workspace. Reply in the language the "
    "user writes in (Hebrew or English are both common). Format with Markdown and put code "
    "in fenced code blocks with a language tag. You cannot run code, browse, or use tools "
    "in this workspace; do not claim to have done so."
)
CHECKPOINT_EVERY_S = 2.0
PING_EVERY_S = 5.0
# Stop reasons that mean the model finished its answer. Anything else
# (max_tokens, refusal, model_context_window_exceeded, pause_turn, tool_use,
# or a value added later) is stored as "incomplete" and labelled in the UI.
COMPLETE_STOP_REASONS = frozenset({"end_turn", "stop_sequence"})

# (event name, JSON-serialisable payload). Raises OSError if the client went away.
Emit = Callable[[str, dict[str, object]], None]
Ping = Callable[[], None]


class Busy(Exception):
    """A reply is already being generated for this conversation."""


def build_context(messages: list[Message], max_chars: int) -> list[Turn]:
    """Turn stored history into provider turns, newest kept first within budget."""
    turns = [
        Turn(m.role, m.content)  # type: ignore[arg-type]
        for m in messages
        if m.content.strip() and m.status in {"complete", "incomplete", "cancelled"}
    ]
    kept: list[Turn] = []
    used = 0
    for turn in reversed(turns):
        if kept and used + len(turn.content) > max_chars:
            break
        kept.append(turn)
        used += len(turn.content)
    kept.reverse()
    # The Messages API requires the first turn to be from the user.
    while kept and kept[0].role != "user":
        kept.pop(0)
    return kept


class ChatService:
    def __init__(
        self,
        store: Store,
        provider: TextProvider,
        max_output_tokens: int,
        max_context_chars: int,
        request_timeout_s: float,
    ):
        self.store = store
        self.provider = provider
        self.max_output_tokens = max_output_tokens
        self.max_context_chars = max_context_chars
        self.request_timeout_s = request_timeout_s
        self._active: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def cancel(self, conversation_id: str) -> bool:
        with self._lock:
            event = self._active.get(conversation_id)
        if event is None:
            return False
        event.set()
        return True

    def is_busy(self, conversation_id: str) -> bool:
        with self._lock:
            return conversation_id in self._active

    def reply(self, conversation_id: str, text: str, emit: Emit, ping: Ping) -> None:
        cancel = threading.Event()
        with self._lock:
            if conversation_id in self._active:
                raise Busy()
            self._active[conversation_id] = cancel
        try:
            self._reply(conversation_id, text, emit, ping, cancel)
        finally:
            with self._lock:
                self._active.pop(conversation_id, None)

    def _reply(
        self,
        conversation_id: str,
        text: str,
        emit: Emit,
        ping: Ping,
        cancel: threading.Event,
    ) -> None:
        conv = self.store.get_conversation(conversation_id)
        if conv is not None and conv.title == DEFAULT_TITLE:
            if not any(
                m.role == "user" for m in self.store.list_messages(conversation_id)
            ):
                conv = self.store.rename_conversation(
                    conversation_id, title_from_message(text)
                )
        user_msg = self.store.add_message(conversation_id, "user", text)
        turns = build_context(
            self.store.list_messages(conversation_id), self.max_context_chars
        )
        assistant = self.store.add_message(
            conversation_id,
            "assistant",
            "",
            status="streaming",
            provider=self.provider.name,
            model=self.provider.model,
            simulated=self.provider.simulated,
        )

        parts: list[str] = []
        client_gone = False

        def send(event: str, data: dict[str, object]) -> None:
            nonlocal client_gone
            if client_gone:
                return
            try:
                emit(event, data)
            except OSError:
                # The browser closed the connection: treat it as a cancel.
                client_gone = True
                cancel.set()

        send(
            "start",
            {
                "conversation": conv.to_dict() if conv else None,
                "user_message": user_msg.to_dict(),
                "assistant_message": assistant.to_dict(),
            },
        )

        status = "complete"
        stop_reason = "end_turn"
        error: str | None = None
        response_model: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        last_checkpoint = last_ping = time.monotonic()
        deadline = time.monotonic() + self.request_timeout_s
        events = self.provider.stream(
            SYSTEM_PROMPT, turns, self.max_output_tokens, cancel, deadline
        )
        try:
            for ev in events:
                if isinstance(ev, TextDelta):
                    parts.append(ev.text)
                    send("delta", {"text": ev.text})
                elif isinstance(ev, ResponseStart):
                    response_model, input_tokens = ev.model, ev.input_tokens
                elif isinstance(ev, Heartbeat):
                    if time.monotonic() - last_ping > PING_EVERY_S and not client_gone:
                        last_ping = time.monotonic()
                        try:
                            ping()
                        except OSError:
                            client_gone = True
                            cancel.set()
                elif isinstance(ev, StreamEnd):
                    stop_reason = ev.stop_reason
                    output_tokens = ev.output_tokens
                if cancel.is_set():
                    stop_reason = "cancelled"
                    break
                if time.monotonic() - last_checkpoint > CHECKPOINT_EVERY_S:
                    self.store.update_message_content(assistant.id, "".join(parts))
                    last_checkpoint = time.monotonic()
            if stop_reason == "cancelled":
                status = "cancelled"
            elif stop_reason not in COMPLETE_STOP_REASONS:
                status = "incomplete"
        except ProviderError as exc:
            status, error, stop_reason = "error", exc.message, "error"
            log.warning("provider error kind=%s status=%s", exc.kind, exc.status)
        except Exception as exc:  # noqa: BLE001 - must always finalise the row
            status, error, stop_reason = "error", "Unexpected server error.", "error"
            # Type only: the exception text could quote conversation content.
            log.error("unexpected error during reply: %s", type(exc).__name__)
        finally:
            # Closes the upstream HTTP response now rather than at GC time.
            close = getattr(events, "close", None)
            if close is not None:
                close()

        final = self.store.finish_message(
            assistant.id,
            "".join(parts),
            status,
            error=error,
            stop_reason=stop_reason,
            response_model=response_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if status == "error":
            send("error", {"message": error or "", "assistant_message": _d(final)})
        else:
            send("done", {"assistant_message": _d(final)})


def _d(msg: Message | None) -> dict[str, object] | None:
    return msg.to_dict() if msg else None
