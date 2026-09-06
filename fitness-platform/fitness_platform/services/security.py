"""Password hashing, CSRF tokens and rate limiting (34).

Password hashing is PBKDF2-HMAC-SHA256 from the standard library. bcrypt or
argon2 would be the usual choice; neither is installable in this environment, so
PBKDF2 with a high iteration count is used and the stored format carries the
algorithm and cost, which is what makes a later migration to argon2 a matter of
re-hashing on next login rather than a schema change.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from ..config import get_settings

_HASH_ALGORITHM = "pbkdf2_sha256"
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    settings = get_settings()
    salt = secrets.token_bytes(_SALT_BYTES)
    iterations = settings.password_iterations
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_HASH_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = stored.split("$")
        if algorithm != _HASH_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str) -> bool:
    try:
        algorithm, iterations_raw, _, _ = stored.split("$")
    except ValueError:
        return True
    return algorithm != _HASH_ALGORITHM or int(iterations_raw) < get_settings().password_iterations


def new_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def sign(value: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(value: str, signature: str) -> bool:
    return hmac.compare_digest(sign(value), signature or "")


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left or "", right or "")


class RateLimiter:
    """A fixed-window counter kept in process memory.

    Good enough for one box and honest about it: behind more than one process
    this needs to move to Redis, which is why every caller goes through this
    class rather than counting inline.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str = "") -> None:
        with self._lock:
            if key:
                self._hits.pop(key, None)
            else:
                self._hits.clear()


limiter = RateLimiter()
