"""Discovery endpoints: run a scan, read the inventory, triage an app."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..connectors import build_connector, close_connector
from ..connectors.base import AuthError, ConnectorError
from ..models import Provider
from ..services.scanner import ScanInProgress
from .deps import AppContext, get_context, require_tenant

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["inventory"])


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
async def start_scan(
    background: BackgroundTasks,
    tenant_id: str = Depends(require_tenant),
    provider: str | None = Query(None, pattern="^(google|microsoft)$"),
    context: AppContext = Depends(get_context),
) -> dict:
    """Kick off a discovery scan.

    With no ``provider``, every provider this tenant has connected is scanned —
    a customer with both Workspace and Entra wants one button, not two.

    Returns immediately: a full Workspace scan is minutes of API calls, and no
    dashboard should hold an HTTP connection open for that. Poll
    ``GET /scans/latest`` for progress.
    """
    connected = await context.repo.list_connected_providers(tenant_id)
    if not connected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This tenant has not connected a provider yet.",
        )

    if provider:
        wanted = Provider(provider)
        if wanted not in connected:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{provider} is not connected for this tenant"
            )
        targets = [wanted]
    else:
        targets = connected

    started = [p for p in targets if not context.scans.is_running(tenant_id, p)]
    if not started:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running")

    async def _run(target: Provider) -> None:
        try:
            await context.scans.run_scan(tenant_id, target, trigger_kind="manual")
        except ScanInProgress:
            pass
        except Exception:  # background tasks swallow exceptions otherwise
            log.exception("Background %s scan for tenant %s failed", target.value, tenant_id)

    for target in started:
        background.add_task(_run, target)
    return {
        "status": "started",
        "tenant_id": tenant_id,
        "providers": [p.value for p in started],
    }


@router.get("/scans/latest")
async def latest_scan(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Most recent scan overall, plus one per provider.

    Both are reported because a customer running Workspace and Entra needs to
    see a stale or failing connection even when the other one just succeeded.
    """
    scan = await context.repo.latest_scan(tenant_id)
    per_provider = await context.repo.latest_scan_per_provider(tenant_id)
    running = [
        p.value for p in await context.repo.list_connected_providers(tenant_id)
        if context.scans.is_running(tenant_id, p)
    ]
    if scan is None:
        return {"status": "never_scanned", "running": running, "by_provider": []}
    return {
        **scan,
        "id": str(scan["id"]),
        "running": running,
        "by_provider": [{**s, "id": str(s["id"])} for s in per_provider],
    }


@router.get("/summary")
async def summary(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """The dashboard header: counts by band, plus the last scan."""
    counts = await context.repo.inventory_summary(tenant_id)
    per_provider = await context.repo.latest_scan_per_provider(tenant_id)
    return {
        "counts": counts,
        "connected_providers": [
            p.value for p in await context.repo.list_connected_providers(tenant_id)
        ],
        "scans_by_provider": [{**s, "id": str(s["id"])} for s in per_provider],
    }


@router.get("/apps")
async def list_apps(
    tenant_id: str = Depends(require_tenant),
    band: str | None = Query(None, pattern="^(low|medium|high)$"),
    app_status: str | None = Query(None, alias="status",
                                   pattern="^(new|approved|blocked|ignored)$"),
    category: str | None = Query(None, max_length=40),
    search: str | None = Query(None, max_length=100),
    provider: str | None = Query(None, pattern="^(google|microsoft)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    context: AppContext = Depends(get_context),
) -> dict:
    apps = await context.repo.list_apps(
        tenant_id, band=band, status=app_status, category=category,
        search=search, provider=provider, limit=limit, offset=offset,
    )
    return {"apps": [{**a, "id": str(a["id"])} for a in apps], "count": len(apps)}


@router.get("/apps/{app_id}")
async def get_app(
    app_id: str,
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    app = await context.repo.get_app(tenant_id, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "App not found")
    return {**app, "id": str(app["id"]), "tenant_id": str(app["tenant_id"])}


class StatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|approved|blocked|ignored)$")
    reviewer: str = ""


@router.patch("/apps/{app_id}")
async def set_app_status(
    app_id: str,
    body: StatusUpdate,
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Triage: approve a sanctioned app, or mark one for removal."""
    if not await context.repo.set_app_status(tenant_id, app_id, body.status, body.reviewer):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "App not found")
    return {"ok": True, "app_id": app_id, "status": body.status}


@router.get("/events")
async def list_events(
    tenant_id: str = Depends(require_tenant),
    limit: int = Query(50, ge=1, le=200),
    context: AppContext = Depends(get_context),
) -> dict:
    """The change feed: new apps, widened scopes, rising risk."""
    events = await context.repo.recent_events(tenant_id, limit)
    return {"events": events}


class RevokeRequest(BaseModel):
    user_emails: list[str] = Field(default_factory=list, max_length=500)
    reviewer: str = ""
    confirm: bool = False


@router.post("/apps/{app_id}/revoke")
async def revoke_app(
    app_id: str,
    body: RevokeRequest,
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Revoke a third-party app's access for the named principals.

    Destructive and not undoable — affected users lose access until they
    re-consent — so it requires ``confirm: true`` and an explicit list. Never
    call this automatically from a scan.

    For Entra apps the list may contain the synthetic principals shown on the
    app detail view: revoking "(all users — admin consent)" removes the
    tenant-wide grant, and "(application — no user)" removes app-only
    permissions. Those two need the optional write permissions on the app
    registration; without them Graph answers 403 and this returns 400.
    """
    if not body.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Revocation is irreversible for the user; resend with confirm=true.",
        )
    if not body.user_emails:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user_emails must not be empty")

    # The app row is the authority on which provider to talk to — the caller
    # should not have to know, and should not be able to redirect us.
    app = await context.repo.get_app(tenant_id, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "App not found")
    provider = Provider(app["provider"])

    client_id, client_secret = context.settings.oauth_client(provider.value)
    creds = await context.repo.load_credentials(
        tenant_id, provider, client_id=client_id, client_secret=client_secret
    )
    if creds is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Tenant has no active {provider.value} connection"
        )

    connector = build_connector(creds, context.settings, concurrency=1)
    revoked: list[str] = []
    failed: dict[str, str] = {}
    try:
        for principal in body.user_emails:
            try:
                await asyncio.to_thread(connector.revoke_grant, principal, app["client_id"])
                revoked.append(principal)
            except AuthError as exc:
                await context.repo.mark_credentials_broken(tenant_id, provider, str(exc))
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            except ConnectorError as exc:
                failed[principal] = str(exc)
    finally:
        close_connector(connector)

    await context.repo.set_app_status(tenant_id, app_id, "blocked", body.reviewer)
    return {"provider": provider.value, "revoked": revoked, "failed": failed}
