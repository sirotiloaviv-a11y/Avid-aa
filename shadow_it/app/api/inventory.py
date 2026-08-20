"""Discovery endpoints: run a scan, read the inventory, triage an app."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..connectors import GoogleWorkspaceConnector
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
    context: AppContext = Depends(get_context),
) -> dict:
    """Kick off a discovery scan.

    Returns immediately: a full-directory scan is minutes of API calls, and no
    dashboard should hold an HTTP connection open for that. Poll
    ``GET /scans/latest`` for progress.
    """
    if context.scans.is_running(tenant_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running")

    async def _run() -> None:
        try:
            await context.scans.run_scan(tenant_id, Provider.GOOGLE, trigger_kind="manual")
        except ScanInProgress:
            pass
        except Exception:  # background tasks swallow exceptions otherwise
            log.exception("Background scan for tenant %s failed", tenant_id)

    background.add_task(_run)
    return {"status": "started", "tenant_id": tenant_id}


@router.get("/scans/latest")
async def latest_scan(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    scan = await context.repo.latest_scan(tenant_id)
    if scan is None:
        return {"status": "never_scanned", "running": context.scans.is_running(tenant_id)}
    return {**scan, "id": str(scan["id"]), "running": context.scans.is_running(tenant_id)}


@router.get("/summary")
async def summary(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """The dashboard header: counts by band, plus the last scan."""
    counts = await context.repo.inventory_summary(tenant_id)
    scan = await context.repo.latest_scan(tenant_id)
    return {
        "counts": counts,
        "last_scan": {**scan, "id": str(scan["id"])} if scan else None,
    }


@router.get("/apps")
async def list_apps(
    tenant_id: str = Depends(require_tenant),
    band: str | None = Query(None, pattern="^(low|medium|high)$"),
    app_status: str | None = Query(None, alias="status",
                                   pattern="^(new|approved|blocked|ignored)$"),
    category: str | None = Query(None, max_length=40),
    search: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    context: AppContext = Depends(get_context),
) -> dict:
    apps = await context.repo.list_apps(
        tenant_id, band=band, status=app_status, category=category,
        search=search, limit=limit, offset=offset,
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
    client_id: str = Field(min_length=1, max_length=300)
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
    """Revoke a third-party app's tokens for the named users.

    Destructive and not undoable — affected users lose access until they
    re-consent — so it requires ``confirm: true`` and an explicit user list.
    Never call this automatically from a scan.
    """
    if not body.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Revocation is irreversible for the user; resend with confirm=true.",
        )
    if not body.user_emails:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user_emails must not be empty")

    creds = await context.repo.load_credentials(
        tenant_id, Provider.GOOGLE,
        client_id=context.settings.google_client_id,
        client_secret=context.settings.google_client_secret,
    )
    if creds is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tenant has no active Google connection")

    connector = GoogleWorkspaceConnector(creds, concurrency=1)
    revoked, failed = [], {}
    for email in body.user_emails:
        try:
            await asyncio.to_thread(connector.revoke_grant, email, body.client_id)
            revoked.append(email)
        except AuthError as exc:
            await context.repo.mark_credentials_broken(tenant_id, Provider.GOOGLE, str(exc))
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except ConnectorError as exc:
            failed[email] = str(exc)

    await context.repo.set_app_status(tenant_id, app_id, "blocked", body.reviewer)
    return {"revoked": revoked, "failed": failed}
