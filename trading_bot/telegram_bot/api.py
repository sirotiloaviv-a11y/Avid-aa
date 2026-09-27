"""Minimal Telegram Bot API client over ``urllib`` (no dependencies).

Only the two methods the bot needs: ``sendMessage`` and ``getUpdates``.
The token is part of every request URL, so errors are re-raised with the
URL scrubbed; a traceback in ``bot.log`` must never contain the token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, cast

from ..config import Secret

# (url, body bytes, timeout) -> (HTTP status, response bytes)
Transport = Callable[[str, bytes, float], "tuple[int, bytes]"]

MAX_MESSAGE_LENGTH = 4096


class TelegramApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        # Network failure, rate limit or server error: try again later.
        return self.status is None or self.status == 429 or self.status >= 500


def _urllib_transport(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data: bytes = response.read()
            return int(response.status), data
    except urllib.error.HTTPError as exc:
        # Telegram puts the useful description in the error body.
        return exc.code, exc.read()


class TelegramClient:
    def __init__(
        self,
        token: Secret,
        *,
        api_base: str = "https://api.telegram.org",
        timeout: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        if not token:
            raise ValueError("Telegram bot token is empty")
        self._token = token
        self._api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _urllib_transport

    def call(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        url = f"{self._api_base}/bot{self._token.get()}/{method}"
        body = json.dumps(params).encode("utf-8")
        try:
            status, raw = self._transport(url, body, timeout or self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = str(exc).replace(self._token.get(), "***")
            raise TelegramApiError(f"{method}: network error: {reason}") from None
        try:
            payload = cast("dict[str, Any]", json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise TelegramApiError(f"{method}: HTTP {status}, non-JSON response", status=status) from None
        if not payload.get("ok"):
            params_out = cast("dict[str, Any]", payload.get("parameters") or {})
            retry_after = params_out.get("retry_after")
            raise TelegramApiError(
                f"{method}: {payload.get('description', 'unknown error')}",
                status=int(payload.get("error_code") or status),
                retry_after=float(retry_after) if retry_after is not None else None,
            )
        return payload.get("result")

    def send_message(
        self, chat_id: str, text: str, *, parse_mode: str = "HTML", silent: bool = False
    ) -> None:
        self.call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "disable_notification": silent,
        })

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        """Long poll. The HTTP timeout is padded past Telegram's own."""
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        result = self.call("getUpdates", params, timeout=timeout + 10)
        return cast("list[dict[str, Any]]", result or [])
