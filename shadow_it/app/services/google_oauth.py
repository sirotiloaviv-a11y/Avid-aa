"""Admin-consent flow: how a customer connects their Workspace in 60 seconds.

    GET  /v1/connect/google        -> redirect the admin to Google
    GET  /v1/connect/google/callback -> exchange the code, store the refresh token

Security properties this flow depends on, none of them optional:

* **Signed state.** The state parameter is an HMAC of (tenant_id, nonce,
  timestamp). An unsigned state is a CSRF hole that lets an attacker bind
  *their* Workspace to *your* tenant, or the reverse.
* **``prompt=consent`` + ``access_type=offline``.** Without both, Google
  returns a refresh token only on the very first authorization, and a
  reconnect silently yields nothing to store.
* **Identity from the id_token, not from a form field.** The admin's email and
  the ``hd`` (hosted domain) claim come from a token Google signed, so a
  customer cannot connect a domain they do not administer.

Least privilege: exactly two Admin SDK scopes, plus openid/email to identify
the consenting admin. Nothing else — admins read the consent screen, and an
over-broad ask is the fastest way to lose a security sale.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from ..connectors.google_workspace import REQUIRED_SCOPES

log = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# openid/email only identify the admin who consented; they grant no data access.
CONSENT_SCOPES: tuple[str, ...] = ("openid", "email", *REQUIRED_SCOPES)

STATE_TTL_SECONDS = 600


class OAuthError(RuntimeError):
    """The consent flow failed in a way the admin needs to see."""


@dataclass(frozen=True)
class ConnectedAdmin:
    email: str
    hosted_domain: str
    refresh_token: str
    granted_scopes: tuple[str, ...]


# ----------------------------------------------------------------- state ---
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

    data = json.loads(payload)
    if time.time() - float(data.get("ts", 0)) > STATE_TTL_SECONDS:
        raise OAuthError("OAuth state expired — start the connection again")
    return str(data["t"])


# ------------------------------------------------------------------ flow ---
def build_authorize_url(
    client_id: str, redirect_uri: str, state: str, login_hint: str = ""
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(CONSENT_SCOPES),
        "access_type": "offline",   # we need a refresh token for scheduled scans
        "prompt": "consent",        # ...and Google only re-issues one if asked
        "include_granted_scopes": "false",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_ENDPOINT}?{httpx.QueryParams(params)}"


async def exchange_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> ConnectedAdmin:
    """Trade the authorization code for a refresh token and the admin's identity."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        # Google's error body names the actual problem (redirect_uri_mismatch
        # is the classic); surface it instead of a generic failure.
        raise OAuthError(f"Token exchange failed ({response.status_code}): {response.text[:300]}")

    payload = response.json()
    refresh_token = payload.get("refresh_token", "")
    if not refresh_token:
        raise OAuthError(
            "Google returned no refresh token. The admin has already granted "
            "this app before — have them remove it at "
            "https://myaccount.google.com/permissions and reconnect."
        )

    claims = _verify_id_token(payload.get("id_token", ""), client_id)
    email = claims.get("email", "")
    hosted_domain = claims.get("hd", "")
    if not hosted_domain:
        raise OAuthError(
            "That is a personal Google account. Connect with a Workspace "
            "super-admin account on the company domain."
        )

    return ConnectedAdmin(
        email=email,
        hosted_domain=hosted_domain,
        refresh_token=refresh_token,
        granted_scopes=tuple(payload.get("scope", "").split()),
    )


def _verify_id_token(raw: str, client_id: str) -> dict:
    if not raw:
        raise OAuthError("No id_token in Google's response — cannot identify the admin")
    try:
        # Verifies signature, issuer, audience and expiry against Google's keys.
        return google_id_token.verify_oauth2_token(raw, google_requests.Request(), client_id)
    except ValueError as exc:
        raise OAuthError(f"Could not verify Google's id_token: {exc}") from exc


async def revoke_refresh_token(refresh_token: str) -> bool:
    """Hand the token back when a customer disconnects or churns.

    Holding a live super-admin token for a company that left is a liability
    with no upside, so disconnect calls this and does not wait to be asked.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    return response.status_code == 200
