"""Google Workspace connector — the Admin SDK side of discovery.

What it does
------------
``directory.users.list``  -> every account in the tenant
``directory.tokens.list`` -> every third-party OAuth client that account has
                             authorized, and the scopes it holds

That second call is the product: it is the only place Google exposes the full
list of apps an employee connected, including ones installed years ago and
never opened since.

Scopes required (least privilege — do not ask for more, admins do read the
consent screen):

    admin.directory.user.readonly    list users
    admin.directory.user.security    read (and revoke) a user's tokens

Auth: either a domain-wide-delegated service account impersonating an admin,
or a refresh token from an admin who ran the OAuth consent flow. Service
accounts are steadier for scheduled scans (no token to lose when the admin
leaves); OAuth is far easier for self-serve onboarding, so the MVP supports
both and defaults to OAuth.

Cost model: tokens.list is one API call per user and does not batch usefully,
so a 2,000-seat tenant is 2,000 calls. That is why this module cares about
concurrency and backoff rather than raw speed.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Iterator

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..models import AppGrant, DirectoryUser, Provider
from .base import AuthError, ConnectorError, DiscoveryReport, ProgressCallback, TenantCredentials

log = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"

# Read-only discovery. admin.directory.user.security is what tokens.list needs;
# it also permits revocation, which is the remediation half of the product.
REQUIRED_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.security",
)

# Google answers rate limits with 429, and sometimes with 403 + a quota reason.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "backendError"}
MAX_ATTEMPTS = 5
USERS_PAGE_SIZE = 500


def build_credentials(creds: TenantCredentials):
    """Turn stored tenant credentials into google-auth credentials."""
    if creds.service_account_info:
        try:
            sa = service_account.Credentials.from_service_account_info(
                creds.service_account_info, scopes=list(REQUIRED_SCOPES)
            )
        except (ValueError, KeyError) as exc:
            raise AuthError(f"Malformed service account key: {exc}") from exc
        if not creds.admin_email:
            raise AuthError(
                "Domain-wide delegation needs an admin to impersonate — set admin_email."
            )
        # DWD only works when impersonating a real admin; the service account
        # itself is not a member of the Workspace domain.
        return sa.with_subject(creds.admin_email)

    if not (creds.refresh_token and creds.client_id and creds.client_secret):
        raise AuthError("No usable Google credentials stored for this tenant.")

    return UserCredentials(
        token=None,
        refresh_token=creds.refresh_token,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        token_uri=TOKEN_URI,
        scopes=list(REQUIRED_SCOPES),
    )


class GoogleWorkspaceConnector:
    """Thread-safe wrapper around the Admin SDK Directory API.

    googleapiclient service objects are *not* thread-safe (the underlying http
    transport is shared), so each worker thread gets its own service built from
    the same credentials. That detail is the difference between a scan that
    works and one that returns other users' results at random under load.
    """

    provider = Provider.GOOGLE

    def __init__(
        self,
        credentials: TenantCredentials,
        concurrency: int = 8,
        max_users: int = 0,
    ):
        self._tenant_creds = credentials
        self._google_creds = build_credentials(credentials)
        self._customer_id = credentials.customer_id or "my_customer"
        self._concurrency = max(1, concurrency)
        self._max_users = max_users
        self._local = threading.local()

    # ------------------------------------------------------------- plumbing
    @property
    def _service(self):
        """One Directory API service per thread, built lazily."""
        service = getattr(self._local, "service", None)
        if service is None:
            service = build(
                "admin",
                "directory_v1",
                credentials=self._google_creds,
                cache_discovery=False,  # avoids the noisy file-cache warning
            )
            self._local.service = service
        return service

    @staticmethod
    def _execute(request, description: str):
        """Execute one API request with backoff on the errors Google expects
        you to retry, and a clear failure on the ones you must not."""
        delay = 1.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return request.execute(num_retries=0)
            except RefreshError as exc:
                raise AuthError(
                    f"Google refused to refresh the tenant's token ({exc}). "
                    "The admin revoked access, changed password, or the app was "
                    "removed from the Workspace allowlist — reconnect required."
                ) from exc
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                reason = _first_reason(exc)
                if status == 401:
                    raise AuthError(f"Unauthorized on {description}: {reason or exc}") from exc
                if status == 403 and reason not in RETRYABLE_REASONS:
                    # Almost always a missing scope or a non-admin subject.
                    raise AuthError(
                        f"Forbidden on {description}: {reason or exc}. Confirm the "
                        "account is a Workspace admin and both required scopes "
                        "were granted."
                    ) from exc
                if status in RETRYABLE_STATUS or reason in RETRYABLE_REASONS:
                    if attempt == MAX_ATTEMPTS:
                        raise ConnectorError(
                            f"{description} still rate-limited after {MAX_ATTEMPTS} attempts"
                        ) from exc
                    # Full jitter: synchronized retries are how you turn one
                    # 429 into a scan-long thundering herd.
                    sleep_for = delay + random.uniform(0, delay)
                    log.warning(
                        "%s got %s (%s); retry %d/%d in %.1fs",
                        description, status, reason or "-", attempt, MAX_ATTEMPTS, sleep_for,
                    )
                    time.sleep(sleep_for)
                    delay = min(delay * 2, 30.0)
                    continue
                raise ConnectorError(f"{description} failed: {exc}") from exc
            except GoogleAuthError as exc:
                raise AuthError(f"Authentication failed on {description}: {exc}") from exc
        raise ConnectorError(f"{description} exhausted retries")

    # ----------------------------------------------------------------- api
    def test_connection(self) -> dict:
        """Prove the credentials work before we store or schedule anything."""
        result = self._execute(
            self._service.users().list(customer=self._customer_id, maxResults=1),
            "users.list (connection test)",
        )
        users = result.get("users", [])
        return {
            "ok": True,
            "customer_id": self._customer_id,
            "sample_domain": users[0].get("primaryEmail", "").split("@")[-1] if users else "",
        }

    def list_users(self, include_suspended: bool = False) -> Iterator[DirectoryUser]:
        """Every account in the tenant, paginated.

        Suspended accounts are skipped by default but their grants still exist
        server-side — set include_suspended=True during offboarding audits,
        where a leaver's live third-party tokens are exactly the point.
        """
        page_token = None
        yielded = 0
        while True:
            response = self._execute(
                self._service.users().list(
                    customer=self._customer_id,
                    maxResults=USERS_PAGE_SIZE,
                    orderBy="email",
                    projection="basic",
                    pageToken=page_token,
                ),
                "users.list",
            )
            for raw in response.get("users", []):
                if raw.get("suspended") and not include_suspended:
                    continue
                yield DirectoryUser(
                    external_id=str(raw.get("id", "")),
                    email=raw.get("primaryEmail", ""),
                    full_name=(raw.get("name") or {}).get("fullName", ""),
                    is_admin=bool(raw.get("isAdmin") or raw.get("isDelegatedAdmin")),
                    is_suspended=bool(raw.get("suspended")),
                    org_unit=raw.get("orgUnitPath", ""),
                )
                yielded += 1
                if self._max_users and yielded >= self._max_users:
                    return
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def list_grants_for_user(self, user: DirectoryUser) -> list[AppGrant]:
        """Third-party apps this one user has authorized.

        ``anonymous: true`` means the client id is not registered to a Google
        Cloud project — Google itself cannot tell you who wrote it. Those are
        the rows a security team wants first.
        """
        response = self._execute(
            self._service.tokens().list(userKey=user.email),
            f"tokens.list({user.email})",
        )
        now = datetime.now(timezone.utc)
        grants: list[AppGrant] = []
        for raw in response.get("items", []):
            client_id = raw.get("clientId", "")
            if not client_id:
                continue
            grants.append(
                AppGrant(
                    client_id=client_id,
                    display_name=raw.get("displayText") or client_id,
                    user_email=user.email,
                    scopes=list(raw.get("scopes", [])),
                    is_anonymous=bool(raw.get("anonymous")),
                    is_native_app=bool(raw.get("nativeApp")),
                    user_is_admin=user.is_admin,
                    observed_at=now,
                )
            )
        return grants

    def list_grants(
        self,
        users: list[DirectoryUser],
        progress: ProgressCallback | None = None,
    ) -> DiscoveryReport:
        """Fan out tokens.list across the directory.

        One user's failure must not sink the scan: a partial inventory with a
        listed error beats a red X and no data.
        """
        report = DiscoveryReport()
        if not users:
            return report

        done = 0
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = {pool.submit(self.list_grants_for_user, u): u for u in users}
            for future in as_completed(futures):
                user = futures[future]
                done += 1
                try:
                    report.grants.extend(future.result())
                    report.users_scanned += 1
                except AuthError:
                    # Credentials died mid-scan; nothing after this can succeed.
                    for pending in futures:
                        pending.cancel()
                    raise
                except ConnectorError as exc:
                    report.errors.append(f"{user.email}: {exc}")
                    log.warning("Skipping %s: %s", user.email, exc)
                if progress:
                    progress(done, len(users))
        return report

    def revoke_grant(self, user_email: str, client_id: str) -> None:
        """Remediation: delete one user's token for one app.

        Irreversible from the app's side — the user must re-consent. Only ever
        call this from an explicit, per-app admin action, never automatically
        from a scan.
        """
        self._execute(
            self._service.tokens().delete(userKey=user_email, clientId=client_id),
            f"tokens.delete({user_email}, {client_id})",
        )
        log.info("Revoked %s for %s", client_id, user_email)


def _first_reason(exc: HttpError) -> str:
    """Pull Google's machine-readable error reason out of an HttpError."""
    try:
        details = exc.error_details  # googleapiclient >= 2.x
        if isinstance(details, list) and details:
            first = details[0]
            if isinstance(first, dict):
                return str(first.get("reason", ""))
    except (AttributeError, ValueError, KeyError):
        pass
    return ""
