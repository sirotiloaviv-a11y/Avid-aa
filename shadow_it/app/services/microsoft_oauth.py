"""Admin-consent flow for Microsoft 365.

Structurally different from Google's, and simpler:

    GET /v1/connect/microsoft/start/{tenant_id} -> the admin consent URL
    GET /v1/connect/microsoft/callback          -> Entra confirms, we store a GUID

Entra's ``/adminconsent`` endpoint grants a multi-tenant application its
*application* permissions across the customer's whole directory in one click by
a Global Administrator. There is no authorization code and no per-customer
refresh token: the redirect just tells us which tenant said yes. From then on
we mint app-only tokens with our own client credentials against that tenant id.

The security consequence is worth stating plainly, because it is a genuine
advantage over the Google side: **the only customer-specific value we store is
a tenant id, which is a public GUID.** A database breach here leaks nothing
usable on its own; an attacker would also need our client secret, which lives
only in the process environment. Compare the Workspace path, where the stored
row *is* a live super-admin credential.

We encrypt the tenant id anyway. One storage path, one decrypt path, no
special case to get wrong later.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from ..connectors.microsoft365 import (
    GRAPH_DEFAULT_SCOPE,
    LOGIN_BASE,
    REQUIRED_APP_ROLES,
    REVOCATION_APP_ROLES,
)
from ..oauth_state import STATE_TTL_SECONDS, OAuthError, make_state, verify_state

log = logging.getLogger(__name__)

__all__ = [
    "REQUIRED_APP_ROLES",
    "REVOCATION_APP_ROLES",
    "ConsentedTenant",
    "OAuthError",
    "STATE_TTL_SECONDS",
    "build_admin_consent_url",
    "make_state",
    "parse_callback",
    "verify_state",
]

# Entra tenant ids are GUIDs. Validating the shape before it reaches a URL
# keeps a hostile redirect from steering our token requests somewhere else.
TENANT_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Entra creates the service principal asynchronously, so the first app-only
# token request after consent can lose the race by a couple of seconds.
CONSENT_PROPAGATION_ATTEMPTS = 3
CONSENT_PROPAGATION_DELAY = 2.0


class ConsentedTenant:
    """The outcome of a successful admin consent: just a directory id."""

    __slots__ = ("tenant_id",)

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def __repr__(self) -> str:
        return f"ConsentedTenant(tenant_id={self.tenant_id!r})"


def build_admin_consent_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the customer's Global Administrator.

    ``/common/`` lets any Entra tenant consent, which is the whole point of a
    multi-tenant registration. The permissions granted are the application
    permissions configured on the registration itself — they are not passed
    here, so the consent screen always matches what the app actually asks for.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{LOGIN_BASE}/common/adminconsent?{httpx.QueryParams(params)}"


def parse_callback(
    tenant: str, state: str, admin_consent: str, error: str, error_description: str, secret: str
) -> tuple[str, ConsentedTenant]:
    """Validate Entra's redirect. Returns (our tenant_id, the consented directory).

    Every failure mode here is one an admin can act on, so each gets its own
    message rather than a generic "connection failed".
    """
    if error:
        if error == "access_denied":
            raise OAuthError(
                "Consent was declined, or the account is not a Global "
                "Administrator. Admin consent for the whole directory can only "
                "be granted by a Global Administrator."
            )
        raise OAuthError(f"Entra reported {error}: {error_description or 'no detail given'}")

    if not state:
        raise OAuthError("Entra's redirect carried no state parameter")
    our_tenant_id = verify_state(state, secret)

    if admin_consent.lower() != "true":
        raise OAuthError("Entra did not confirm admin consent for this directory")
    if not TENANT_ID_PATTERN.match(tenant or ""):
        raise OAuthError(f"Entra returned an unusable directory id: {tenant!r}")

    return our_tenant_id, ConsentedTenant(tenant_id=tenant.lower())


async def verify_app_only_access(tenant_id: str, client_id: str, client_secret: str) -> dict:
    """Confirm the consent actually took, before we store anything.

    Entra propagates a new service principal asynchronously — for the first few
    seconds after consent, a token request can still fail. That is why this
    retries briefly instead of declaring failure on the first attempt.
    """
    body = ""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(CONSENT_PROPAGATION_ATTEMPTS):
            response = await client.post(
                f"{LOGIN_BASE}/{tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": GRAPH_DEFAULT_SCOPE,
                    "grant_type": "client_credentials",
                },
            )
            if response.status_code == 200:
                return response.json()
            body = response.text[:300]
            log.info(
                "App-only token not available yet for tenant %s (attempt %d/%d)",
                tenant_id, attempt + 1, CONSENT_PROPAGATION_ATTEMPTS,
            )
            if attempt + 1 < CONSENT_PROPAGATION_ATTEMPTS:
                await asyncio.sleep(CONSENT_PROPAGATION_DELAY)

    raise OAuthError(
        f"Could not obtain an app-only token for directory {tenant_id} after "
        f"{CONSENT_PROPAGATION_ATTEMPTS} attempts: {body}"
    )
