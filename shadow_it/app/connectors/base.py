"""The contract every identity provider connector implements.

Keep this narrow. A connector's whole job is: authenticate as the customer's
admin, enumerate users, enumerate third-party grants, and hand back
``AppGrant`` objects. Scoring, storage and scheduling live elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from ..models import AppGrant, DirectoryUser, DiscoveredApp, Provider


class ConnectorError(RuntimeError):
    """A connector could not talk to the provider."""


class AuthError(ConnectorError):
    """Credentials are missing, expired, or lack the required scopes.

    Distinct from ConnectorError because it is not retryable: it means the
    tenant has to reconnect, and the UI should say so.
    """


@dataclass
class TenantCredentials:
    """Decrypted, in-memory only. Never log or serialize this.

    One shape covers both providers because what changes between them is which
    fields are populated, not what the scanner does with them:

    * Google, OAuth: ``refresh_token`` + our client_id/client_secret.
    * Google, domain-wide delegation: ``service_account_info`` + admin_email.
    * Microsoft, client credentials: ``directory_tenant_id`` + our
      client_id/client_secret. Nothing customer-specific is secret here — the
      customer's tenant id is a public GUID — which is a real advantage over
      holding a super-admin refresh token.
    """

    provider: Provider
    admin_email: str = ""
    # Either an OAuth refresh token from the admin-consent flow...
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    # ...or a domain-wide-delegated service account key (dict form).
    service_account_info: dict | None = None
    customer_id: str = "my_customer"
    # Entra ID (Microsoft) directory the client credentials are used against.
    directory_tenant_id: str = ""

    def __repr__(self) -> str:  # keep secrets out of tracebacks and logs
        return (
            f"TenantCredentials(provider={self.provider.value!r}, "
            f"admin_email={self.admin_email!r}, secrets=<redacted>)"
        )


ProgressCallback = Callable[[int, int], None]


class Connector(Protocol):
    provider: Provider

    def test_connection(self) -> dict:
        """Cheap call proving the credentials work. Raises AuthError if not."""

    def list_users(self) -> Iterable[DirectoryUser]:
        ...

    def list_grants(
        self, users: list[DirectoryUser], progress: ProgressCallback | None = None
    ) -> Iterable[AppGrant]:
        ...


@dataclass
class DiscoveryReport:
    grants: list[AppGrant] = field(default_factory=list)
    users_scanned: int = 0
    errors: list[str] = field(default_factory=list)


def aggregate(grants: Iterable[AppGrant], provider: Provider) -> list[DiscoveredApp]:
    """Collapse per-principal grants into one row per client id.

    Provider-neutral on purpose: a connector's raw output stays inspectable on
    its own, which is what you want when a customer disputes a finding, and
    both connectors get identical aggregation semantics for free.
    """
    apps: dict[str, DiscoveredApp] = {}
    for grant in grants:
        app = apps.get(grant.client_id)
        if app is None:
            app = DiscoveredApp(
                client_id=grant.client_id,
                display_name=grant.display_name,
                provider=provider,
            )
            apps[grant.client_id] = app
        app.absorb(grant)
    return list(apps.values())
