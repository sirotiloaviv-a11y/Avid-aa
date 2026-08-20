"""Provider-neutral domain types.

Connectors (Google today, Microsoft 365 next) translate their own API shapes
into these, so the risk engine and the storage layer never learn a vendor's
vocabulary. Adding a provider means adding a connector, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Provider(str, Enum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class RiskBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AppStatus(str, Enum):
    NEW = "new"          # discovered, nobody has looked at it yet
    APPROVED = "approved"  # sanctioned by the customer — stops alerting
    BLOCKED = "blocked"    # customer wants it gone; revocation is manual in MVP
    IGNORED = "ignored"    # noise, e.g. the customer's own internal script


@dataclass(frozen=True)
class DirectoryUser:
    """A person in the customer's directory."""

    external_id: str
    email: str
    full_name: str = ""
    is_admin: bool = False
    is_suspended: bool = False
    org_unit: str = ""


@dataclass
class AppGrant:
    """One user having authorized one third-party app.

    This is the atomic fact the Admin SDK gives us: user X granted client Y
    scopes Z. Everything else in the product is an aggregation of these.
    """

    client_id: str
    display_name: str
    user_email: str
    scopes: list[str] = field(default_factory=list)
    # Google flags a client that is not registered in any Cloud project.
    # Those are the ones nobody can vouch for — a strong Shadow IT signal.
    is_anonymous: bool = False
    is_native_app: bool = False
    user_is_admin: bool = False
    observed_at: datetime | None = None


@dataclass
class DiscoveredApp:
    """All grants for one client id, collapsed into the thing you review."""

    client_id: str
    display_name: str
    provider: Provider = Provider.GOOGLE
    is_anonymous: bool = False
    is_native_app: bool = False
    scopes: set[str] = field(default_factory=set)
    user_emails: set[str] = field(default_factory=set)
    admin_user_emails: set[str] = field(default_factory=set)

    @property
    def install_count(self) -> int:
        return len(self.user_emails)

    def absorb(self, grant: AppGrant) -> None:
        self.scopes.update(grant.scopes)
        self.user_emails.add(grant.user_email)
        if grant.user_is_admin:
            self.admin_user_emails.add(grant.user_email)
        # Any single anonymous/native observation applies to the client itself.
        self.is_anonymous = self.is_anonymous or grant.is_anonymous
        self.is_native_app = self.is_native_app or grant.is_native_app
        if grant.display_name and not self.display_name:
            self.display_name = grant.display_name


@dataclass
class RiskAssessment:
    """The output of the risk engine — a score you can argue with.

    ``reasons`` exists because a security tool that says "high risk" without
    saying why gets ignored by the third week.
    """

    score: int
    band: RiskBand
    category: str
    reasons: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "score": self.score,
            "band": self.band.value,
            "category": self.category,
            "reasons": self.reasons,
            "capabilities": self.capabilities,
        }


@dataclass
class ScanResult:
    tenant_id: str
    users_scanned: int = 0
    grants_found: int = 0
    apps_found: int = 0
    new_apps: int = 0
    errors: list[str] = field(default_factory=list)
