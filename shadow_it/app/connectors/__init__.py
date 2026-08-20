"""Identity-provider connectors: Google Workspace and Microsoft 365.

Only the provider-neutral surface is re-exported here. Import a concrete
connector from its own module (``.google_workspace``, ``.microsoft365``) when
you genuinely need the class — that way importing this package never drags in
a provider SDK you are not using.
"""

from .base import (
    AuthError,
    Connector,
    ConnectorError,
    DiscoveryReport,
    TenantCredentials,
    aggregate,
)
from .factory import build_connector, close_connector

__all__ = [
    "AuthError",
    "Connector",
    "ConnectorError",
    "DiscoveryReport",
    "TenantCredentials",
    "aggregate",
    "build_connector",
    "close_connector",
]
