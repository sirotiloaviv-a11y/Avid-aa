"""Signed, expiring OAuth state — shared by both onboarding flows.

The provider redirects the admin's browser back to a callback that cannot be
authenticated any other way: the browser has no API key. The ``state``
parameter is therefore the entire access control on that endpoint. Unsigned,
it is a CSRF hole that lets an attacker bind their directory to your tenant —
or yours to theirs.

So: HMAC over (tenant_id, nonce, issued-at), verified in constant time, and
expired after ten minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

STATE_TTL_SECONDS = 600


class OAuthError(RuntimeError):
    """The consent flow failed in a way the admin needs to see."""


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_state(tenant_id: str, secret: str) -> str:
    payload = json.dumps(
        {"t": tenant_id, "n": secrets.token_urlsafe(12), "ts": int(time.time())},
        separators=(",", ":"),
    ).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload, secret)}"


def verify_state(state: str, secret: str) -> str:
    """Return the tenant_id carried by a valid state, else raise."""
    try:
        body, signature = state.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError) as exc:
        raise OAuthError("Malformed OAuth state") from exc

    if not hmac.compare_digest(_sign(payload, secret), signature):
        raise OAuthError("OAuth state signature mismatch — possible CSRF attempt")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OAuthError("Malformed OAuth state") from exc

    if time.time() - float(data.get("ts", 0)) > STATE_TTL_SECONDS:
        raise OAuthError("OAuth state expired — start the connection again")
    return str(data["t"])
