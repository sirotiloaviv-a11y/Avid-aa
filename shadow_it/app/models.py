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


# Microsoft has two grant shapes that have no per-user principal, so they get
# synthetic ones. They are never real mailboxes, and ``absorb`` keeps them out
# of the user count so "8 users" always means eight people.
TENANT_WIDE_PRINCIPAL = "(all users — admin consent)"
APPLICATION_PRINCIPAL = "(application — no user)"


class GrantType(str, Enum):
    """How an app came to hold its permissions.

    Google only ever produces DELEGATED: a person clicked Allow. Entra ID adds
    two shapes that are strictly worse, and the distinction drives the score:

    * TENANT_WIDE — an admin consented on behalf of everyone. No employee opted
      in and no employee can opt out.
    * APPLICATION — app-only permissions. There is no user in the loop at all;
      the app reads the tenant at 3am whether anyone is signed in or not.
    """

    DELEGATED = "delegated"
    TENANT_WIDE = "tenant_wide"
    APPLICATION = "application"


@dataclass
class AppGrant:
    """One principal having authorized one third-party app.

    This is the atomic fact a provider gives us: principal X granted client Y
    scopes Z. Everything else in the product is an aggregation of these. The
    principal is usually a person; for Entra's tenant-wide and app-only grants
    it is one of the synthetic constants above.
    """

    client_id: str
    display_name: str
    user_email: str
    scopes: list[str] = field(default_factory=list)
    # Google flags a client that is not registered in any Cloud project;
    # Microsoft's equivalent is a service principal with no verified publisher.
    # Either way: nobody can vouch for it — a strong Shadow IT signal.
    is_anonymous: bool = False
    is_native_app: bool = False
    user_is_admin: bool = False
    grant_type: GrantType = GrantType.DELEGATED
    observed_at: datetime | None = None


@dataclass
class DiscoveredApp:
    """All grants for one client id, collapsed into the thing you review."""

    client_id: str
    display_name: str
    provider: Provider = Provider.GOOGLE
    is_anonymous: bool = False
    is_native_app: bool = False
    # Entra only: an admin consented for the whole directory, or the app holds
    # app-only permissions that need no signed-in user.
    tenant_wide_consent: bool = False
    has_application_permissions: bool = False
    scopes: set[str] = field(default_factory=set)
    user_emails: set[str] = field(default_factory=set)
    admin_user_emails: set[str] = field(default_factory=set)

    @property
    def install_count(self) -> int:
        return len(self.user_emails)

    def absorb(self, grant: AppGrant) -> None:
        self.scopes.update(grant.scopes)
        if grant.grant_type is GrantType.TENANT_WIDE:
            self.tenant_wide_consent = True
        elif grant.grant_type is GrantType.APPLICATION:
            self.has_application_permissions = True
        else:
            # Only real people count towards install_count; a tenant-wide
            # consent is one grant row but affects everybody, and an app-only
            # grant affects nobody in particular. Folding either into the user
            # set would make the number meaningless.
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
