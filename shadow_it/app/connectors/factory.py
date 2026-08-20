"""Pick a connector for a provider.

One place that knows which class serves which provider, so the scanner, the
connect endpoints and the revoke endpoint cannot drift apart on the answer.

The concrete connectors are imported *inside* the function on purpose. Each one
pulls in a provider SDK — googleapiclient for Workspace, nothing but httpx for
Graph — and a deployment that only sells one of them should not have to install
(or import, or keep patched) the other's dependency tree. It also keeps the
risk engine and the Graph parsers testable without the Google libraries present.
"""

from __future__ import annotations

from ..config import Settings
from ..models import Provider
from .base import AuthError, Connector, TenantCredentials


def build_connector(
    credentials: TenantCredentials,
    settings: Settings,
    concurrency: int | None = None,
    max_users: int | None = None,
) -> Connector:
    """Construct the connector for ``credentials.provider``.

    Both connectors are synchronous; the caller runs them in a worker thread.
    """
    workers = settings.scan_concurrency if concurrency is None else concurrency
    limit = settings.scan_max_users if max_users is None else max_users

    if credentials.provider is Provider.MICROSOFT:
        from .microsoft365 import MicrosoftGraphConnector

        return MicrosoftGraphConnector(credentials, concurrency=workers, max_users=limit)

    if credentials.provider is Provider.GOOGLE:
        try:
            from .google_workspace import GoogleWorkspaceConnector
        except ImportError as exc:  # the Google SDK is not installed
            raise AuthError(
                "The Google Workspace connector needs google-api-python-client "
                f"and google-auth: {exc}"
            ) from exc

        return GoogleWorkspaceConnector(credentials, concurrency=workers, max_users=limit)

    raise AuthError(f"No connector for provider {credentials.provider}")


def close_connector(connector: Connector) -> None:
    """Release a connector's transport if it holds one (Graph does, Google does not)."""
    closer = getattr(connector, "close", None)
    if callable(closer):
        closer()
