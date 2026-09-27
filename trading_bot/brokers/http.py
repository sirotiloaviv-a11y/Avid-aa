"""Small JSON-over-HTTPS client for broker REST APIs (urllib, no deps).

Idempotent reads are retried on network errors, rate limits and 5xx.
**Order-placing calls are never retried here**: a timeout does not mean the
order was rejected, and a blind retry can double a position. Callers
reconcile against the broker's positions instead.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from ..utils.logger import get_logger
from .base import BrokerError

log = get_logger(__name__)

# (method, url, headers, body, timeout) -> (status, response headers, body)
HttpTransport = Callable[[str, str, Mapping[str, str], "bytes | None", float],
                         "tuple[int, Mapping[str, str], bytes]"]


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data: bytes = response.read()
            return int(response.status), dict(response.headers), data
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BrokerError(f"{method} {url.split('?')[0]}: network error: {exc}", retryable=True) from None


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 15.0,
        read_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport or urllib_transport
        self.timeout = timeout
        self.read_attempts = read_attempts
        self._sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        raw_body: bytes | None = None,
    ) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        data = raw_body if raw_body is not None else (
            json.dumps(body, separators=(",", ":")).encode() if body is not None else None)
        all_headers = {"Accept": "application/json", **(headers or {})}
        if data is not None:
            all_headers.setdefault("Content-Type", "application/json")
        attempts = self.read_attempts if method == "GET" else 1
        for attempt in range(1, attempts + 1):
            try:
                return self._once(method, url, all_headers, data)
            except BrokerError as exc:
                if not exc.retryable or attempt == attempts:
                    raise
                delay = exc.retry_after or min(8.0, 0.5 * 2 ** attempt)
                log.warning("%s %s failed (%s); retry %d/%d in %.1fs",
                            method, path, exc, attempt, attempts, delay)
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _once(self, method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> Any:
        status, response_headers, raw = self._transport(method, url, headers, data, self.timeout)
        path = url.split("?")[0].removeprefix(self.base_url)
        if status == 429 or status >= 500:
            retry_after = response_headers.get("Retry-After") or response_headers.get("retry-after")
            raise BrokerError(f"{method} {path}: HTTP {status}", retryable=True, status=status,
                              retry_after=float(retry_after) if retry_after else None)
        try:
            payload = json.loads(raw) if raw else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BrokerError(f"{method} {path}: HTTP {status}, non-JSON response", status=status) from None
        if status >= 400:
            raise BrokerError(f"{method} {path}: HTTP {status}: {str(payload)[:300]}", status=status)
        return payload
