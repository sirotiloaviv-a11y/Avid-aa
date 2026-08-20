"""Envelope encryption for the credentials we hold on behalf of tenants.

A refresh token for a Workspace super-admin is the crown jewel of this product:
whoever holds it can read the customer's whole directory. It must never sit in
Postgres in plaintext, never appear in a log line, and never come back out of
the API. This module is the only place that decrypts.

Rotation: put the new key in ENCRYPTION_KEY and move the previous one into
ENCRYPTION_KEYS. New writes use the new key; old rows still decrypt. Re-encrypt
lazily (``needs_rotation``) or with a one-off backfill, then drop the old key.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CryptoError(RuntimeError):
    """Raised when a secret cannot be decrypted with any configured key."""


@dataclass(frozen=True)
class SecretBox:
    """Encrypts/decrypts small secrets (refresh tokens, client secrets)."""

    primary: Fernet
    all_keys: MultiFernet
    key_id: str

    @classmethod
    def from_keys(cls, primary_key: str, retired_keys: list[str] | None = None) -> "SecretBox":
        if not primary_key:
            raise CryptoError("ENCRYPTION_KEY is not set")
        try:
            primary = Fernet(primary_key.encode())
            retired = [Fernet(k.encode()) for k in (retired_keys or []) if k]
        except (ValueError, TypeError) as exc:  # malformed base64 / wrong length
            raise CryptoError(f"Invalid Fernet key: {exc}") from exc
        return cls(
            primary=primary,
            all_keys=MultiFernet([primary, *retired]),
            key_id=key_fingerprint(primary_key),
        )

    def encrypt(self, plaintext: str) -> bytes:
        return self.primary.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes | memoryview) -> str:
        try:
            return self.all_keys.decrypt(bytes(ciphertext)).decode("utf-8")
        except InvalidToken as exc:
            raise CryptoError(
                "Could not decrypt secret with any configured key — was "
                "ENCRYPTION_KEY rotated without keeping the old key in "
                "ENCRYPTION_KEYS?"
            ) from exc

    def needs_rotation(self, ciphertext: bytes | memoryview) -> bool:
        """True when the row was written under a retired key."""
        try:
            self.primary.decrypt(bytes(ciphertext))
        except InvalidToken:
            return True
        return False


def key_fingerprint(key: str) -> str:
    """Short, non-reversible id for a key, safe to store next to the ciphertext."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def hash_api_key(raw: str) -> str:
    """API keys are stored hashed — a database leak must not yield live keys."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
