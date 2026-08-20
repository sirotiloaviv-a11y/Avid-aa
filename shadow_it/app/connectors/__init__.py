"""Identity-provider connectors. Google today; Microsoft 365 is next."""

from .base import AuthError, Connector, ConnectorError, DiscoveryReport, TenantCredentials
from .google_workspace import REQUIRED_SCOPES, GoogleWorkspaceConnector, aggregate

__all__ = [
    "AuthError",
    "Connector",
    "ConnectorError",
    "DiscoveryReport",
    "TenantCredentials",
    "GoogleWorkspaceConnector",
    "REQUIRED_SCOPES",
    "aggregate",
]
