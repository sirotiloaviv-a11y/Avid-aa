"""The contract every identity provider connector implements.

Keep this narrow. A connector's whole job is: authenticate as the customer's
admin, enumerate users, enumerate third-party grants, and hand back
``AppGrant`` objects. Scoring, storage and scheduling live elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from ..models import AppGrant, DirectoryUser, Provider


class ConnectorError(RuntimeError):
    """A connector could not talk to the provider."""


class AuthError(ConnectorError):
    """Credentials are missing, expired, or lack the required scopes.

    Distinct from ConnectorError because it is not retryable: it means the
    tenant has to reconnect, and the UI should say so.
    """


@dataclass
class TenantCredentials:
    """Decrypted, in-memory only. Never log or serialize this."""

    provider: Provider
    admin_email: str = ""
    # Either an OAuth refresh token from the admin-consent flow...
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    # ...or a domain-wide-delegated service account key (dict form).
    service_account_info: dict | None = None
    customer_id: str = "my_customer"

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
