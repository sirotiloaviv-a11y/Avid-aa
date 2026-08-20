"""Microsoft 365 connector — Entra ID (Azure AD) app-consent discovery.

Why this looks nothing like the Google connector
------------------------------------------------
Google exposes app grants *per user*: one ``tokens.list`` call per employee, so
a 2,000-seat scan is 2,000 calls. Entra exposes them as directory-wide
collections, so the same scan is a handful of paginated reads no matter how big
the company is. Same product, an order of magnitude cheaper.

    GET /users                             the directory
    GET /directoryRoles?$expand=members    who is privileged
    GET /servicePrincipals                 every app identity in the tenant,
                                           plus each API's appRole id -> name map
    GET /oauth2PermissionGrants            delegated consent (a person clicked Allow)
    GET /servicePrincipals/{id}/appRoleAssignments
                                           app-only permissions, per third-party app

Entra also has two grant shapes Google simply does not have, and both are worse
than anything ``tokens.list`` can return:

* **Tenant-wide consent** (``consentType: AllPrincipals``) — an admin consented
  on behalf of every employee. Nobody opted in; nobody can opt out.
* **Application permissions** (app role assignments) — app-only access with no
  user in the loop at all. It keeps reading the tenant after the employee who
  introduced it has left.

Auth: a single multi-tenant app registration, admin-consented by the customer,
then client credentials against *their* tenant id. Nothing customer-specific is
secret — a tenant id is a public GUID — which is a much smaller liability than
holding a Workspace super-admin refresh token.

Application permissions required on the registration (least privilege):

    Application.Read.All   read service principals and their app role assignments
    Directory.Read.All     read users, directory roles and delegated grants

Revocation additionally needs ``DelegatedPermissionGrant.ReadWrite.All`` and
``AppRoleAssignment.ReadWrite.All``. Both are deliberately optional: discovery
works without them, and a read-only consent screen is far easier to sell.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

import httpx

from ..models import APPLICATION_PRINCIPAL, TENANT_WIDE_PRINCIPAL, DirectoryUser, Provider
from .base import AuthError, ConnectorError, DiscoveryReport, ProgressCallback, TenantCredentials
from .graph_model import (
    MICROSOFT_FIRST_PARTY_TENANT,
    SP_FIELDS,
    USER_FIELDS,
    ServicePrincipal,
    build_grants,
    parse_user,
)

log = logging.getLogger(__name__)

__all__ = [
    "GRAPH_BASE",
    "GRAPH_DEFAULT_SCOPE",
    "LOGIN_BASE",
    "MICROSOFT_FIRST_PARTY_TENANT",
    "REQUIRED_APP_ROLES",
    "REVOCATION_APP_ROLES",
    "MicrosoftGraphConnector",
    "ServicePrincipal",
    "build_grants",
    "parse_user",
]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"
GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"

REQUIRED_APP_ROLES: tuple[str, ...] = ("Application.Read.All", "Directory.Read.All")
REVOCATION_APP_ROLES: tuple[str, ...] = (
    "DelegatedPermissionGrant.ReadWrite.All",
    "AppRoleAssignment.ReadWrite.All",
)

PAGE_SIZE = 999
MAX_ATTEMPTS = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Graph's way of saying "your app registration is missing a permission".
PERMISSION_ERROR_CODES = {"Authorization_RequestDenied", "Authorization_IdentityNotFound"}

# ------------------------------------------------------------- connector ---
class MicrosoftGraphConnector:
    """Thread-safe Graph client with a cached app-only token.

    Synchronous, like the Google connector, so the scanner treats both the same
    way (one ``asyncio.to_thread`` call). Only the per-app-role-assignment leg
    fans out, and that is bounded by the number of third-party apps, not users.
    """

    provider = Provider.MICROSOFT

    def __init__(
        self,
        credentials: TenantCredentials,
        concurrency: int = 8,
        max_users: int = 0,
        include_microsoft_apps: bool = False,
        timeout: float = 30.0,
    ):
        if not credentials.directory_tenant_id:
            raise AuthError("No Entra tenant id stored for this customer.")
        if not (credentials.client_id and credentials.client_secret):
            raise AuthError(
                "MICROSOFT_CLIENT_ID/MICROSOFT_CLIENT_SECRET are not configured."
            )
        self._creds = credentials
        self._concurrency = max(1, concurrency)
        self._max_users = max_users
        self._include_microsoft_apps = include_microsoft_apps
        self._client = httpx.Client(timeout=timeout)
        self._token: str = ""
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MicrosoftGraphConnector":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------- auth
    def _access_token(self) -> str:
        """Client-credentials token, cached until a minute before it expires."""
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            response = self._client.post(
                f"{LOGIN_BASE}/{self._creds.directory_tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": self._creds.client_id,
                    "client_secret": self._creds.client_secret,
                    "scope": GRAPH_DEFAULT_SCOPE,
                    "grant_type": "client_credentials",
                },
            )
            if response.status_code != 200:
                # invalid_client = our secret expired (they do, every 6-24
                # months); invalid_grant/unauthorized_client = the customer
                # removed our enterprise application.
                raise AuthError(
                    f"Entra refused client credentials for tenant "
                    f"{self._creds.directory_tenant_id}: {response.text[:300]}"
                )
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expires_at = time.monotonic() + int(payload.get("expires_in", 3600)) - 60
            return self._token

    # --------------------------------------------------------- transport
    def _request(self, method: str, url: str, **kwargs) -> dict:
        """One Graph call, with the backoff Microsoft's throttling requires."""
        if not url.startswith("http"):
            url = f"{GRAPH_BASE}{url}"

        # Popped once, not per attempt: a caller-supplied header must survive a retry.
        extra_headers = kwargs.pop("headers", {})
        delay = 1.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            headers.update(extra_headers)
            response = self._client.request(method, url, headers=headers, **kwargs)

            if response.status_code in (200, 201):
                return response.json() if response.content else {}
            if response.status_code == 204:
                return {}

            code, message = _graph_error(response)

            if response.status_code == 401:
                # Force a token refresh once; a stale cached token is the only
                # benign cause and it costs one extra round trip to rule out.
                with self._token_lock:
                    self._token, self._token_expires_at = "", 0.0
                if attempt == 1:
                    continue
                raise AuthError(f"Graph rejected our token on {url}: {message}")
            if response.status_code == 403 or code in PERMISSION_ERROR_CODES:
                raise AuthError(
                    f"Graph denied {url}: {message or code}. The customer's admin "
                    f"consent is missing or incomplete — required application "
                    f"permissions are {', '.join(REQUIRED_APP_ROLES)}."
                )
            if response.status_code == 404:
                raise ConnectorError(f"Graph returned 404 for {url}: {message}")
            if response.status_code in RETRYABLE_STATUS:
                if attempt == MAX_ATTEMPTS:
                    raise ConnectorError(
                        f"{url} still throttled after {MAX_ATTEMPTS} attempts: {message}"
                    )
                # Graph tells you exactly how long to wait; honour it, and add
                # jitter so parallel workers do not resume in lockstep.
                retry_after = _retry_after(response)
                sleep_for = retry_after if retry_after else delay + random.uniform(0, delay)
                log.warning(
                    "Graph %s on %s (%s); retry %d/%d in %.1fs",
                    response.status_code, url, code or "-", attempt, MAX_ATTEMPTS, sleep_for,
                )
                time.sleep(sleep_for)
                delay = min(delay * 2, 60.0)
                continue

            raise ConnectorError(f"Graph {response.status_code} on {url}: {message}")

        raise ConnectorError(f"{url} exhausted retries")

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """Walk an OData collection via @odata.nextLink."""
        payload = self._request("GET", path, params=params)
        while True:
            for item in payload.get("value", []):
                yield item
            next_link = payload.get("@odata.nextLink")
            if not next_link:
                return
            # nextLink is an absolute URL and already carries the query string.
            payload = self._request("GET", next_link)

    # --------------------------------------------------------------- api
    def test_connection(self) -> dict:
        """Prove consent landed before we store or schedule anything."""
        payload = self._request(
            "GET", "/organization", params={"$select": "id,displayName,verifiedDomains"}
        )
        orgs = payload.get("value", [])
        org = orgs[0] if orgs else {}
        domains = [
            d.get("name", "")
            for d in org.get("verifiedDomains", [])
            if d.get("isDefault") or d.get("isInitial")
        ]
        return {
            "ok": True,
            "tenant_id": self._creds.directory_tenant_id,
            "organization": org.get("displayName", ""),
            "sample_domain": domains[0] if domains else "",
        }

    def list_privileged_user_ids(self) -> frozenset[str]:
        """Members of any activated directory role.

        A grant made by a Global Administrator inherits that reach, so the risk
        engine weighs it heavily — but only if we know who the admins are.
        Failing here degrades the scan rather than ending it: an inventory
        without admin flags still beats no inventory.
        """
        try:
            ids: set[str] = set()
            for role in self._paginate("/directoryRoles", {"$expand": "members"}):
                for member in role.get("members", []):
                    if member.get("id"):
                        ids.add(str(member["id"]))
            return frozenset(ids)
        except ConnectorError as exc:
            log.warning("Could not read directory roles (%s); admin flags unavailable", exc)
            return frozenset()

    def list_users(self, include_suspended: bool = False) -> Iterator[DirectoryUser]:
        privileged = self.list_privileged_user_ids()
        yielded = 0
        for raw in self._paginate("/users", {"$select": USER_FIELDS, "$top": PAGE_SIZE}):
            user = parse_user(raw, privileged)
            if user.is_suspended and not include_suspended:
                continue
            if not user.email:
                continue
            yield user
            yielded += 1
            if self._max_users and yielded >= self._max_users:
                return

    def list_service_principals(self) -> dict[str, ServicePrincipal]:
        """Every app identity in the directory, keyed by object id."""
        principals: dict[str, ServicePrincipal] = {}
        for raw in self._paginate(
            "/servicePrincipals", {"$select": SP_FIELDS, "$top": PAGE_SIZE}
        ):
            principal = ServicePrincipal(raw)
            if principal.object_id:
                principals[principal.object_id] = principal
        return principals

    def list_delegated_grants(self) -> list[dict]:
        """Directory-wide delegated consent. One collection, however big the tenant."""
        return list(self._paginate("/oauth2PermissionGrants", {"$top": PAGE_SIZE}))

    def list_app_role_assignments(self, sp_object_id: str) -> list[dict]:
        """App-only permissions held *by* one service principal."""
        return list(
            self._paginate(f"/servicePrincipals/{sp_object_id}/appRoleAssignments",
                           {"$top": PAGE_SIZE})
        )

    def list_grants(
        self,
        users: list[DirectoryUser],
        progress: ProgressCallback | None = None,
    ) -> DiscoveryReport:
        """Full discovery pass.

        ``users`` is only used to put names to principal ids — unlike Google,
        it does not drive the number of API calls.
        """
        report = DiscoveryReport()
        report.users_scanned = len(users)
        users_by_id = {u.external_id: u for u in users if u.external_id}

        principals = self.list_service_principals()
        delegated = self.list_delegated_grants()

        # App-only permissions need one call per app. Restrict to third-party,
        # enabled apps: a real tenant carries hundreds of Microsoft-owned
        # service principals that are not Shadow IT by definition.
        candidates = [
            p for p in principals.values()
            if p.in_scope(self._include_microsoft_apps) and p.enabled
        ]
        assignments: dict[str, list[dict]] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = {
                pool.submit(self.list_app_role_assignments, p.object_id): p for p in candidates
            }
            for future in as_completed(futures):
                principal = futures[future]
                done += 1
                try:
                    found = future.result()
                    if found:
                        assignments[principal.object_id] = found
                except AuthError:
                    for pending in futures:
                        pending.cancel()
                    raise
                except ConnectorError as exc:
                    report.errors.append(f"{principal.display_name}: {exc}")
                    log.warning("Skipping app roles for %s: %s", principal.display_name, exc)
                if progress:
                    progress(done, len(candidates))

        report.grants = build_grants(
            service_principals=principals,
            delegated_grants=delegated,
            app_role_assignments=assignments,
            users_by_id=users_by_id,
            include_microsoft_apps=self._include_microsoft_apps,
        )
        log.info(
            "Entra tenant %s: %d app identities, %d delegated grants, %d apps with "
            "app-only permissions",
            self._creds.directory_tenant_id, len(principals), len(delegated), len(assignments),
        )
        return report

    # -------------------------------------------------------- remediation
    def revoke_grant(self, user_email: str, client_id: str) -> None:
        """Remove one app's access.

        Three cases, because Entra has three grant shapes:

        * a named user  -> delete that user's delegated grant only
        * tenant-wide   -> delete the AllPrincipals grant, cutting off everyone
        * application   -> delete the app role assignments (app-only access)

        Needs the optional write permissions; without them Graph answers 403
        and the caller sees an AuthError naming what is missing.
        """
        principal = self._service_principal_by_app_id(client_id)

        if user_email == APPLICATION_PRINCIPAL:
            for assignment in self.list_app_role_assignments(principal.object_id):
                resource_id = assignment.get("resourceId")
                assignment_id = assignment.get("id")
                if resource_id and assignment_id:
                    self._request(
                        "DELETE",
                        f"/servicePrincipals/{resource_id}/appRoleAssignedTo/{assignment_id}",
                    )
            log.info("Revoked app-only permissions for %s", client_id)
            return

        target_principal_id = ""
        if user_email != TENANT_WIDE_PRINCIPAL:
            target_principal_id = self._user_id(user_email)

        grants = list(
            self._paginate(f"/servicePrincipals/{principal.object_id}/oauth2PermissionGrants")
        )
        for grant in grants:
            is_tenant_wide = str(grant.get("consentType") or "") == "AllPrincipals"
            if user_email == TENANT_WIDE_PRINCIPAL and not is_tenant_wide:
                continue
            if target_principal_id and str(grant.get("principalId") or "") != target_principal_id:
                continue
            self._request("DELETE", f"/oauth2PermissionGrants/{grant['id']}")
        log.info("Revoked %s for %s", client_id, user_email)

    def _service_principal_by_app_id(self, app_id: str) -> ServicePrincipal:
        payload = self._request(
            "GET",
            "/servicePrincipals",
            params={"$filter": f"appId eq '{_odata_literal(app_id)}'", "$select": SP_FIELDS},
        )
        items = payload.get("value", [])
        if not items:
            raise ConnectorError(f"No service principal in this tenant for appId {app_id}")
        return ServicePrincipal(items[0])

    def _user_id(self, user_email: str) -> str:
        payload = self._request("GET", f"/users/{user_email}", params={"$select": "id"})
        user_id = str(payload.get("id", ""))
        if not user_id:
            raise ConnectorError(f"No such user in this tenant: {user_email}")
        return user_id


# ----------------------------------------------------------------- utils ---
def _graph_error(response: httpx.Response) -> tuple[str, str]:
    """Graph's structured error, or a truncated body when it is not JSON."""
    try:
        error = response.json().get("error", {})
        return str(error.get("code", "")), str(error.get("message", ""))
    except (ValueError, AttributeError):
        return "", response.text[:300]


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        # Cap it: Graph occasionally suggests waits longer than a scan should hold.
        return min(float(raw), 120.0) if raw else 0.0
    except ValueError:
        return 0.0


def _odata_literal(value: str) -> str:
    """Escape a string for an OData filter (single quotes double up)."""
    return value.replace("'", "''")
