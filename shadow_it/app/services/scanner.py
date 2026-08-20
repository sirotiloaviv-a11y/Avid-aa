"""The scan: credentials in, scored inventory out.

Sequence, and why it is this order:

    load credentials -> list users -> list grants (fan-out) -> aggregate by
    client id -> score against tenant policy -> persist -> diff -> close scan

Directory size is written before scoring because the risk engine reads "12
users" differently at a 40-person startup than at a 4,000-person company.

Both connectors are synchronous, so the whole connector leg runs in a worker
thread. FastAPI's event loop stays free to serve the dashboard while a
2,000-seat Workspace scan grinds through tokens.list.

The two providers cost wildly different amounts for the same answer — Google is
one API call per employee, Entra is a handful of directory-wide reads — but
that difference is entirely inside the connector. From here they are the same
four steps.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..config import Settings
from ..connectors import aggregate, build_connector, close_connector
from ..connectors.base import AuthError, ConnectorError
from ..models import Provider, ScanResult
from ..risk import assess_all
from .repository import Repository

log = logging.getLogger(__name__)


class ScanInProgress(RuntimeError):
    """A scan for this tenant is already running."""


class ScanService:
    def __init__(self, repo: Repository, settings: Settings):
        self._repo = repo
        self._settings = settings
        # In-process guard. One instance is the MVP's deployment shape; when
        # this grows to multiple workers, swap for a Postgres advisory lock
        # (pg_try_advisory_lock on hashtext(tenant_id)) — same semantics.
        self._running: set[str] = set()
        self._lock = asyncio.Lock()

    async def run_scan(
        self,
        tenant_id: str,
        provider: Provider = Provider.GOOGLE,
        trigger_kind: str = "manual",
    ) -> ScanResult:
        # Keyed by tenant *and* provider: a customer running both Workspace and
        # Entra should be able to scan them at the same time, and one slow
        # Workspace scan must not block the cheap Entra one behind it.
        key = f"{tenant_id}:{provider.value}"
        async with self._lock:
            if key in self._running:
                raise ScanInProgress(
                    f"A {provider.value} scan is already running for tenant {tenant_id}"
                )
            self._running.add(key)
        try:
            return await self._run(tenant_id, provider, trigger_kind)
        finally:
            async with self._lock:
                self._running.discard(key)

    def is_running(self, tenant_id: str, provider: Provider | None = None) -> bool:
        if provider is not None:
            return f"{tenant_id}:{provider.value}" in self._running
        return any(key.startswith(f"{tenant_id}:") for key in self._running)

    # ------------------------------------------------------------------
    async def _run(self, tenant_id: str, provider: Provider, trigger_kind: str) -> ScanResult:
        result = ScanResult(tenant_id=tenant_id)
        started_at = datetime.now(timezone.utc)
        scan_id = await self._repo.start_scan(tenant_id, provider, trigger_kind)

        client_id, client_secret = self._settings.oauth_client(provider.value)
        credentials = await self._repo.load_credentials(
            tenant_id, provider, client_id=client_id, client_secret=client_secret
        )
        if credentials is None:
            await self._repo.finish_scan(
                scan_id,
                "failed",
                errors=[f"No active {provider.value} credentials — tenant must connect first."],
            )
            result.errors.append(f"No active {provider.value} credentials for this tenant.")
            return result

        connector = None
        try:
            connector = build_connector(credentials, self._settings)

            # --- 1. directory ------------------------------------------
            users = await asyncio.to_thread(lambda: list(connector.list_users()))
            log.info(
                "Tenant %s (%s): %d users in the directory",
                tenant_id, provider.value, len(users),
            )
            user_ids = await self._repo.upsert_users(tenant_id, users, provider)
            await self._repo.set_directory_size(tenant_id, len(users))
            result.users_scanned = len(users)

            # --- 2. grants ---------------------------------------------
            report = await asyncio.to_thread(connector.list_grants, users)
            result.grants_found = len(report.grants)
            result.errors.extend(report.errors)

            # --- 3. aggregate and score --------------------------------
            apps = aggregate(report.grants, provider)
            policy = await self._repo.load_policy(tenant_id)
            scored = assess_all(apps, policy)
            result.apps_found = len(scored)

            # --- 4. persist --------------------------------------------
            grants_by_client: dict[str, list] = {}
            for grant in report.grants:
                grants_by_client.setdefault(grant.client_id, []).append(grant)

            for app, assessment in scored:
                outcome = await self._repo.upsert_app(tenant_id, app, assessment, scan_id)
                if outcome["is_new"]:
                    result.new_apps += 1
                await self._repo.upsert_grants(
                    tenant_id,
                    outcome["app_id"],
                    grants_by_client.get(app.client_id, []),
                    user_ids,
                )

            # Anything not seen this pass was revoked between scans.
            await self._repo.mark_stale_grants_revoked(tenant_id, started_at)

        except AuthError as exc:
            # Not retryable: the customer has to reconnect, so say so loudly
            # and stop scheduling scans against a dead token.
            log.error("Tenant %s credentials rejected: %s", tenant_id, exc)
            await self._repo.mark_credentials_broken(tenant_id, provider, str(exc))
            await self._repo.finish_scan(scan_id, "failed", errors=[str(exc)])
            result.errors.append(str(exc))
            return result
        except ConnectorError as exc:
            log.exception("Tenant %s %s scan failed", tenant_id, provider.value)
            await self._repo.finish_scan(
                scan_id, "failed", users_scanned=result.users_scanned, errors=[str(exc)]
            )
            result.errors.append(str(exc))
            return result
        finally:
            if connector is not None:
                close_connector(connector)

        status = "partial" if result.errors else "success"
        await self._repo.finish_scan(
            scan_id,
            status,
            users_scanned=result.users_scanned,
            grants_found=result.grants_found,
            apps_found=result.apps_found,
            new_apps=result.new_apps,
            errors=result.errors[:50],
        )
        log.info(
            "Tenant %s %s scan %s: %d users, %d grants, %d apps (%d new)",
            tenant_id, provider.value, status, result.users_scanned,
            result.grants_found, result.apps_found, result.new_apps,
        )
        return result


class Scheduler:
    """Periodic re-scan of every active tenant.

    A cron container or a managed scheduler is the better answer at scale, but
    a solo developer deploying one container gets recurring scans for free
    here, and the loop is small enough to reason about.
    """

    def __init__(self, scans: ScanService, repo: Repository, interval_hours: int):
        self._scans = scans
        self._repo = repo
        self._interval = max(1, interval_hours) * 3600
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._interval <= 0:
            return
        self._task = asyncio.create_task(self._loop(), name="shadow-it-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        # Let the API finish coming up before the first sweep.
        await asyncio.sleep(60)
        while True:
            try:
                for tenant in await self._repo.list_tenants(active_only=True):
                    tenant_id = str(tenant["id"])
                    # A customer can have Workspace and Entra connected at once
                    # (an acquisition is the usual reason); scan both.
                    for provider in await self._repo.list_connected_providers(tenant_id):
                        if self._scans.is_running(tenant_id, provider):
                            continue
                        try:
                            await self._scans.run_scan(
                                tenant_id, provider, trigger_kind="scheduled"
                            )
                        except (ScanInProgress, ConnectorError) as exc:
                            log.warning(
                                "Scheduled %s scan for %s skipped: %s",
                                provider.value, tenant_id, exc,
                            )
            except asyncio.CancelledError:
                raise
            except Exception:  # a scheduler that dies silently is worse than a noisy one
                log.exception("Scheduler sweep failed; continuing")
            await asyncio.sleep(self._interval)
