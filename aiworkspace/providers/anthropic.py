"""Anthropic Messages API adapter over raw HTTPS (standard library only).

The official SDK is the preferred client, but this project is dependency-free
and the package registries were unreachable when it was written; see README.

Sources used (live docs at platform.claude.com were blocked by the build
environment's network policy, so the Anthropic-published reference bundled
with Claude Code's claude-api skill, version 2.1.283, was used instead):
  * curl/examples.md, "Streaming (SSE)" and "Required Headers": request shape
    and the SSE event sequence.
  * typescript/claude-api/streaming.md, "Stream Event Types": message_delta
    carries stop_reason and usage.
  * shared/error-codes.md: HTTP status / error.type table and retryability.
  * python/claude-api/README.md, "Stop Reasons".
Canonical online equivalents: https://platform.claude.com/docs/en/build-with-claude/streaming
and https://platform.claude.com/docs/en/api/errors.

  POST {base}/v1/messages
  headers: x-api-key, anthropic-version: 2023-06-01, content-type: application/json
  body: {model, max_tokens, system, messages, stream: true}
  SSE events: message_start (message.model, message.usage), content_block_start,
  content_block_delta (text_delta; thinking_delta etc. are not displayed),
  content_block_stop, message_delta (delta.stop_reason, usage.output_tokens),
  message_stop, ping, error. Other event types are treated as keep-alives.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import IO, Callable, Iterator

from .base import (
    Heartbeat,
    ProviderError,
    ResponseStart,
    StreamEnd,
    StreamEvent,
    TextDelta,
    Turn,
)

API_VERSION = "2023-06-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Hard ceiling on automatic retries per user message (AIWS_MAX_RETRIES <= this).
MAX_RETRIES_CAP = 3
MAX_RETRY_WAIT_S = 10.0
READ_TIMEOUT_S = 30.0

_STATUS_KIND = {
    400: "bad_request",
    401: "auth",
    402: "billing",
    403: "permission",
    404: "not_found",
    408: "timeout",
    413: "too_large",
    429: "rate_limit",
    529: "overloaded",
}

_TYPE_KIND = {
    "invalid_request_error": "bad_request",
    "authentication_error": "auth",
    "billing_error": "billing",
    "permission_error": "permission",
    "not_found_error": "not_found",
    "request_too_large": "too_large",
    "rate_limit_error": "rate_limit",
    "overloaded_error": "overloaded",
    "api_error": "server",
    "timeout_error": "timeout",
}

_FRIENDLY = {
    "auth": "The API key was rejected. Check ANTHROPIC_API_KEY in aiworkspace/.env.",
    "permission": "This API key is not allowed to use the configured model.",
    "billing": "The Anthropic account has a billing problem.",
    "not_found": "The configured model was not found. Check AIWS_MODEL.",
    "bad_request": "The model provider rejected the request.",
    "too_large": "The conversation is too large for the model provider.",
    "rate_limit": "The model provider is rate limiting requests. Try again shortly.",
    "overloaded": "The model provider is overloaded. Try again shortly.",
    "server": "The model provider had an internal error. Try again shortly.",
    "network": "Could not reach the model provider. Check your network connection.",
    "timeout": "The model provider took too long to respond.",
    "protocol": "The model provider sent a response this app could not read.",
}


def _error_from_body(status: int | None, body: bytes) -> ProviderError:
    err_type = ""
    detail = ""
    try:
        payload = json.loads(body.decode("utf-8"))
        err = payload.get("error") or {}
        err_type = str(err.get("type", ""))
        detail = str(err.get("message", ""))[:300]
    except (ValueError, AttributeError, UnicodeDecodeError):
        pass
    kind = _TYPE_KIND.get(err_type) or _STATUS_KIND.get(status or 0)
    if kind is None:
        kind = "server" if status is None or status >= 500 else "bad_request"
    message = _FRIENDLY[kind]
    # Upstream detail helps with bad_request/not_found; it never contains the key.
    if detail and kind in {"bad_request", "not_found", "permission", "too_large"}:
        message = f"{message} ({detail})"
    return ProviderError(kind, message, status)  # type: ignore[arg-type]


def iter_sse(lines: IO[bytes]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) pairs from a text/event-stream byte source."""
    event = ""
    data: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data or event:
                yield event, "\n".join(data)
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    if data or event:
        yield event, "\n".join(data)


Opener = Callable[[urllib.request.Request, float], IO[bytes]]


def _default_opener(req: urllib.request.Request, timeout: float) -> IO[bytes]:
    resp: IO[bytes] = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    return resp


class AnthropicProvider:
    name = "anthropic"
    simulated = False

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        fallbacks: str = "off",
        max_retries: int = 2,
        opener: Opener = _default_opener,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        if not 0 <= max_retries <= MAX_RETRIES_CAP:
            raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES_CAP}")
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._fallbacks = fallbacks
        self._max_retries = max_retries
        self._open = opener
        self._sleep = sleep

    def __repr__(self) -> str:  # never include the key
        return f"AnthropicProvider(model={self.model!r})"

    def _request(
        self, system: str, turns: list[Turn], max_tokens: int
    ) -> urllib.request.Request:
        # The standard, non-beta Messages request. No thinking/effort/tools
        # parameters are sent, so the model's own defaults apply.
        body: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [{"role": t.role, "content": t.content} for t in turns],
        }
        if system:
            body["system"] = system
        headers = {
            "content-type": "application/json",
            "accept": "text/event-stream",
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
        }
        if self._fallbacks == "default":
            # Opt-in beta (AIWS_ANTHROPIC_FALLBACKS=default): re-runs a
            # classifier-declined request on Anthropic's recommended fallback
            # model inside the same call. Off by default.
            body["fallbacks"] = "default"
            headers["anthropic-beta"] = FALLBACK_BETA
        return urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _open_with_retry(
        self, req: urllib.request.Request, cancel: threading.Event, deadline: float
    ) -> IO[bytes]:
        """Open the stream. Retries happen only when the API rejected the request
        (429/5xx/529 status) or the connection was never established, so at most
        one attempt per user message can generate (and bill) output."""
        attempts = 1 + self._max_retries
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("timeout", _FRIENDLY["timeout"])
            retry_after: float | None = None
            safe_to_retry = False
            try:
                return self._open(req, min(READ_TIMEOUT_S, remaining))
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read()
                except (OSError, ValueError):
                    body = b""
                finally:
                    exc.close()
                err = _error_from_body(exc.code, body)
                safe_to_retry = err.retryable
                header = exc.headers.get("retry-after") if exc.headers else None
                try:
                    retry_after = float(header) if header else None
                except ValueError:
                    retry_after = None
            except (TimeoutError, socket.timeout):
                err = ProviderError("timeout", _FRIENDLY["timeout"])
            except urllib.error.URLError as exc:
                err = ProviderError("network", _FRIENDLY["network"])
                # DNS failure or refused connection: the request never left.
                safe_to_retry = isinstance(
                    exc.reason, (ConnectionRefusedError, socket.gaierror)
                )
            except OSError:
                err = ProviderError("network", _FRIENDLY["network"])
            if not safe_to_retry or attempt == attempts or cancel.is_set():
                raise err
            wait = min(
                retry_after if retry_after is not None else 0.5 * 2**attempt,
                MAX_RETRY_WAIT_S,
            )
            if time.monotonic() + wait >= deadline:
                raise err
            self._sleep(wait)
        raise AssertionError("unreachable")

    def stream(
        self,
        system: str,
        turns: list[Turn],
        max_tokens: int,
        cancel: threading.Event,
        deadline: float,
    ) -> Iterator[StreamEvent]:
        resp = self._open_with_retry(
            self._request(system, turns, max_tokens), cancel, deadline
        )
        stop_reason = ""
        output_tokens: int | None = None
        finished = False
        try:
            for event, data in iter_sse(resp):
                if cancel.is_set():
                    yield StreamEnd("cancelled", output_tokens)
                    return
                if time.monotonic() > deadline:
                    raise ProviderError("timeout", _FRIENDLY["timeout"])
                if not data:
                    continue
                try:
                    payload = json.loads(data)
                except ValueError as exc:
                    raise ProviderError("protocol", _FRIENDLY["protocol"]) from exc
                if not isinstance(payload, dict):
                    raise ProviderError("protocol", _FRIENDLY["protocol"])
                kind = payload.get("type", event)
                if kind == "error":
                    raise _error_from_body(None, data.encode("utf-8"))
                if kind == "message_start":
                    message = payload.get("message") or {}
                    usage = message.get("usage") or {}
                    output_tokens = _int_or_none(usage.get("output_tokens"))
                    yield ResponseStart(
                        model=message.get("model") or None,
                        input_tokens=_int_or_none(usage.get("input_tokens")),
                    )
                elif kind == "content_block_delta":
                    delta = payload.get("delta") or {}
                    text = (
                        delta.get("text", "")
                        if delta.get("type") == "text_delta"
                        else ""
                    )
                    # thinking_delta / signature_delta / input_json_delta are not
                    # shown or stored; they only prove the stream is alive.
                    yield TextDelta(text) if text else Heartbeat()
                elif kind == "message_delta":
                    delta = payload.get("delta") or {}
                    stop_reason = delta.get("stop_reason") or stop_reason
                    usage = payload.get("usage") or {}
                    # Keep the latest figure the API reports for this message.
                    output_tokens = (
                        _int_or_none(usage.get("output_tokens")) or output_tokens
                    )
                    yield Heartbeat()
                elif kind == "message_stop":
                    finished = True
                    break
                else:
                    # ping, content_block_start/stop (text, thinking,
                    # redacted_thinking) and any event type added later.
                    yield Heartbeat()
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderError("timeout", _FRIENDLY["timeout"]) from exc
        except OSError as exc:
            raise ProviderError("network", _FRIENDLY["network"]) from exc
        except UnicodeDecodeError as exc:
            raise ProviderError("protocol", _FRIENDLY["protocol"]) from exc
        finally:
            resp.close()
        if not finished:
            raise ProviderError(
                "protocol", "The response from the model provider ended early."
            )
        yield StreamEnd(stop_reason or "end_turn", output_tokens)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
