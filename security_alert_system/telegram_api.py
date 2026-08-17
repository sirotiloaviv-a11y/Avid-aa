"""Thin async wrapper over the Telegram Bot API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"
# Telegram hard-caps a text message at 4096 UTF-16 code units.
MAX_MESSAGE_CHARS = 4000


class TelegramError(RuntimeError):
    """A call the API rejected for a non-transient reason."""


class TelegramClient:
    def __init__(self, token: str, timeout: int = 20, max_retries: int = 4):
        if not token:
            raise ValueError("A Telegram bot token is required.")
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TelegramClient":
        self._client = httpx.AsyncClient(
            base_url=f"{API_ROOT}/bot{self._token}",
            timeout=httpx.Timeout(self._timeout, read=self._timeout + 45),
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        files: dict[str, Any] | None = None,
        read_timeout: float | None = None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("TelegramClient must be used as an async context manager.")

        delay = 2.0
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.post(
                    f"/{method}",
                    data=payload or {},
                    files=files,
                    timeout=read_timeout or self._client.timeout,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                log.warning("%s network error (attempt %d/%d): %s",
                            method, attempt, self._max_retries, exc)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if response.status_code == 429:
                retry_after = _retry_after(response)
                log.warning("%s rate-limited; sleeping %.1fs.", method, retry_after)
                await asyncio.sleep(retry_after)
                continue

            if response.status_code >= 500:
                last_error = TelegramError(f"{method}: HTTP {response.status_code}")
                log.warning("%s server error %d (attempt %d/%d).",
                            method, response.status_code, attempt, self._max_retries)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            try:
                body = response.json()
            except ValueError as exc:
                raise TelegramError(f"{method}: non-JSON response") from exc

            if not body.get("ok"):
                # 4xx other than 429 means the request itself is wrong —
                # a bad chat id, a bot that is not in the channel, etc.
                raise TelegramError(
                    f"{method} failed: {body.get('error_code')} {body.get('description')}"
                )
            return body.get("result")

        raise TelegramError(f"{method}: giving up after {self._max_retries} attempts") from last_error

    # ------------------------------------------------------------- methods
    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def get_updates(
        self,
        offset: int = 0,
        long_poll_seconds: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": long_poll_seconds}
        if offset:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = _json_list(allowed_updates)
        result = await self._call(
            "getUpdates", payload, read_timeout=long_poll_seconds + 20
        )
        return result or []

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        return await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:MAX_MESSAGE_CHARS],
                "parse_mode": parse_mode,
                "disable_web_page_preview": str(disable_web_page_preview).lower(),
                "disable_notification": str(disable_notification).lower(),
            },
        )

    async def send_photo(
        self,
        chat_id: str,
        image: bytes,
        caption: str = "",
        filename: str = "snapshot.jpg",
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        return await self._call(
            "sendPhoto",
            {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": parse_mode},
            files={"photo": (filename, image, "image/jpeg")},
        )


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json()["parameters"]["retry_after"])
    except (ValueError, KeyError, TypeError):
        return float(response.headers.get("Retry-After", 5))


def _json_list(values: list[str]) -> str:
    return json.dumps(values)
