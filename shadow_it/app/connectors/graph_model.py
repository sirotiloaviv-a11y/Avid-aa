"""Graph payloads -> our domain model. Pure translation, no HTTP.

Split out of ``microsoft365.py`` so the part most likely to be wrong is the
part easiest to test: these functions run against captured Graph responses with
no network, no credentials, and no third-party imports at all.

Three Graph collections have to be joined to answer "which third-party apps can
read this company's data?":

* ``servicePrincipals``      — the app identities, and the only place an
                               appRole GUID is given a human name
* ``oauth2PermissionGrants`` — delegated consent, per user or tenant-wide
* ``appRoleAssignments``     — app-only permissions, per app

The join is done here, once, so the connector stays a thin HTTP client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..models import (
    APPLICATION_PRINCIPAL,
    TENANT_WIDE_PRINCIPAL,
    AppGrant,
    DirectoryUser,
    GrantType,
)

# What the parsers below expect Graph to have returned; kept next to them so a
# new field is added to the $select and the parser in one place.
USER_FIELDS = "id,userPrincipalName,displayName,mail,accountEnabled,department"
SP_FIELDS = (
    "id,appId,displayName,appOwnerOrganizationId,verifiedPublisher,publisherName,"
    "servicePrincipalType,accountEnabled,appRoles,signInAudience"
)

# The tenant that owns every Microsoft first-party service principal. Outlook,
# Teams and friends are not Shadow IT, and a real tenant has hundreds of them.
MICROSOFT_FIRST_PARTY_TENANT = "f8cdef31-a31e-4b4a-93e4-5f571e91255a"


class ServicePrincipal:
    """An app identity in the customer's directory.

    Doubles as the appRole id -> permission-name dictionary: app role
    assignments reference a role by GUID, and the only place those GUIDs are
    named is the *resource* service principal's ``appRoles`` collection. Since
    we already page through every service principal, the map comes free.
    """

    __slots__ = (
        "object_id", "app_id", "display_name", "publisher_name",
        "verified_publisher", "owner_tenant_id", "sp_type", "enabled", "app_roles",
    )

    def __init__(self, raw: Mapping[str, Any]):
        self.object_id: str = str(raw.get("id", ""))
        self.app_id: str = str(raw.get("appId", ""))
        self.display_name: str = str(raw.get("displayName") or self.app_id)
        self.publisher_name: str = str(raw.get("publisherName") or "")
        verified = raw.get("verifiedPublisher") or {}
        self.verified_publisher: str = str(verified.get("displayName") or "")
        self.owner_tenant_id: str = str(raw.get("appOwnerOrganizationId") or "")
        self.sp_type: str = str(raw.get("servicePrincipalType") or "")
        self.enabled: bool = raw.get("accountEnabled") is not False
        self.app_roles: dict[str, str] = {
            str(role.get("id", "")): str(role.get("value") or role.get("displayName") or "")
            for role in (raw.get("appRoles") or [])
            if role.get("id")
        }

    @property
    def is_microsoft_first_party(self) -> bool:
        return self.owner_tenant_id.lower() == MICROSOFT_FIRST_PARTY_TENANT

    @property
    def is_managed_identity(self) -> bool:
        # Azure infrastructure, not something an employee connected.
        return self.sp_type == "ManagedIdentity"

    @property
    def publisher_unverified(self) -> bool:
        """Nobody official vouches for this app.

        The direct analogue of Google's ``anonymous`` flag. It is also true of
        an app registered inside the customer's own directory, which is correct:
        an employee's personal registration holding Mail.Read on the tenant is
        precisely the case this product exists to surface.
        """
        return not self.verified_publisher

    def in_scope(self, include_microsoft_apps: bool = False) -> bool:
        if self.is_managed_identity:
            return False
        if self.is_microsoft_first_party and not include_microsoft_apps:
            return False
        return True


# --------------------------------------------------------------- parsing ---
# Pure functions: no HTTP, no clock beyond one timestamp. Everything that turns
# Graph's shape into ours lives here so it can be tested against captured
# payloads instead of a live tenant.
def build_grants(
    service_principals: Mapping[str, ServicePrincipal],
    delegated_grants: Iterable[Mapping[str, Any]],
    app_role_assignments: Mapping[str, list[Mapping[str, Any]]],
    users_by_id: Mapping[str, DirectoryUser],
    include_microsoft_apps: bool = False,
) -> list[AppGrant]:
    """Turn Graph's three collections into our flat list of grants."""
    now = datetime.now(timezone.utc)
    role_names: dict[str, str] = {}
    for principal in service_principals.values():
        role_names.update(principal.app_roles)

    grants: list[AppGrant] = []

    for raw in delegated_grants:
        client = service_principals.get(str(raw.get("clientId", "")))
        if client is None or not client.in_scope(include_microsoft_apps):
            continue
        # Graph packs the permissions into one space-separated string.
        scopes = str(raw.get("scope") or "").split()
        if not scopes:
            continue

        if str(raw.get("consentType") or "") == "AllPrincipals":
            grants.append(
                _grant(client, TENANT_WIDE_PRINCIPAL, scopes, GrantType.TENANT_WIDE, now)
            )
            continue

        principal_id = str(raw.get("principalId") or "")
        user = users_by_id.get(principal_id)
        if user is None:
            # A grant whose principal we did not enumerate (disabled account, or
            # SCAN_MAX_USERS cut the list short). Keep it: dropping evidence
            # because a lookup missed would understate the app's reach.
            email = f"(unknown principal {principal_id[:8]})" if principal_id else "(unknown)"
            grants.append(_grant(client, email, scopes, GrantType.DELEGATED, now))
            continue

        grant = _grant(client, user.email, scopes, GrantType.DELEGATED, now)
        grant.user_is_admin = user.is_admin
        grants.append(grant)

    for sp_object_id, assignments in app_role_assignments.items():
        client = service_principals.get(sp_object_id)
        if client is None or not client.in_scope(include_microsoft_apps):
            continue
        permissions = sorted(
            {
                role_names.get(
                    str(a.get("appRoleId", "")),
                    f"(unknown app role {str(a.get('appRoleId', ''))[:8]})",
                )
                for a in assignments
                if a.get("appRoleId")
            }
        )
        if permissions:
            grants.append(
                _grant(client, APPLICATION_PRINCIPAL, permissions, GrantType.APPLICATION, now)
            )

    return grants


def _grant(
    client: ServicePrincipal,
    principal: str,
    scopes: list[str],
    grant_type: GrantType,
    observed_at: datetime,
) -> AppGrant:
    return AppGrant(
        # The appId is the stable, human-quotable identifier — the one that
        # shows up in Entra's UI and in Microsoft's own docs. The object id is
        # per-directory and means nothing to the customer.
        client_id=client.app_id or client.object_id,
        display_name=client.display_name,
        user_email=principal,
        scopes=scopes,
        is_anonymous=client.publisher_unverified,
        is_native_app=False,  # Entra does not expose a native/installed flag
        grant_type=grant_type,
        observed_at=observed_at,
    )


def parse_user(raw: Mapping[str, Any], privileged_ids: frozenset[str]) -> DirectoryUser:
    user_id = str(raw.get("id", ""))
    return DirectoryUser(
        external_id=user_id,
        email=str(raw.get("userPrincipalName") or raw.get("mail") or ""),
        full_name=str(raw.get("displayName") or ""),
        is_admin=user_id in privileged_ids,
        is_suspended=raw.get("accountEnabled") is False,
        org_unit=str(raw.get("department") or ""),
    )
