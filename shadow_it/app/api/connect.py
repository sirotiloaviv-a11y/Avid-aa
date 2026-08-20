"""Provider connection endpoints — the customer-facing onboarding path."""

from __future__ import annotations

import asyncio
import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from ..connectors import GoogleWorkspaceConnector
from ..connectors.base import AuthError, ConnectorError, TenantCredentials
from ..models import Provider
from ..services import google_oauth
from .deps import AppContext, get_context, require_tenant

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/connect", tags=["connect"])

CALLBACK_PATH = "/v1/connect/google/callback"


def _redirect_uri(context: AppContext) -> str:
    return f"{context.settings.public_base_url}{CALLBACK_PATH}"


# Path is /google/start/{tenant_id} rather than /google/{tenant_id} so that a
# tenant id can never shadow the fixed /google/callback route.
@router.get("/google/start/{tenant_id}")
async def start_google_connect(
    tenant_id: str = Depends(require_tenant),
    login_hint: str = Query("", description="Pre-fill the admin's email"),
    context: AppContext = Depends(get_context),
) -> dict:
    """Build the consent URL for the customer's Workspace super-admin."""
    tenant = await context.repo.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    state = google_oauth.make_state(tenant_id, context.settings.api_key)
    url = google_oauth.build_authorize_url(
        client_id=context.settings.google_client_id,
        redirect_uri=_redirect_uri(context),
        state=state,
        login_hint=login_hint,
    )
    # Returned as JSON rather than a 307: this endpoint needs an API key, and
    # the admin's browser does not have one. The dashboard calls it, then sends
    # the admin to authorize_url.
    return {"authorize_url": url, "expires_in": google_oauth.STATE_TTL_SECONDS}


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    context: AppContext = Depends(get_context),
):
    """Google redirects the admin back here.

    Unauthenticated by necessity — the admin's browser has no API key — which
    is exactly why the signed ``state`` is doing the access control.
    """
    if error:
        return _page("Connection cancelled", f"Google reported: {error}")
    if not (code and state):
        return _page("Connection failed", "Google's redirect was missing code or state.")

    try:
        tenant_id = google_oauth.verify_state(state, context.settings.api_key)
        admin = await google_oauth.exchange_code(
            code=code,
            client_id=context.settings.google_client_id,
            client_secret=context.settings.google_client_secret,
            redirect_uri=_redirect_uri(context),
        )
    except google_oauth.OAuthError as exc:
        log.warning("Google connect failed: %s", exc)
        return _page("Connection failed", str(exc))

    # Prove the credentials actually work before storing them. Discovering a
    # missing scope at 3am during the first scheduled scan is a support ticket;
    # discovering it here is a sentence on screen.
    probe = TenantCredentials(
        provider=Provider.GOOGLE,
        admin_email=admin.email,
        refresh_token=admin.refresh_token,
        client_id=context.settings.google_client_id,
        client_secret=context.settings.google_client_secret,
    )
    try:
        connector = GoogleWorkspaceConnector(probe, concurrency=1, max_users=1)
        await _to_thread(connector.test_connection)
    except (AuthError, ConnectorError) as exc:
        await google_oauth.revoke_refresh_token(admin.refresh_token)
        return _page(
            "Connection failed",
            f"{exc} The account must be a Workspace admin with both requested "
            "permissions granted.",
        )

    await context.repo.save_credentials(
        tenant_id=tenant_id,
        provider=Provider.GOOGLE,
        admin_email=admin.email,
        secret=admin.refresh_token,
        method="oauth_refresh_token",
        granted_scopes=admin.granted_scopes,
    )
    log.info("Tenant %s connected Google Workspace as %s", tenant_id, admin.email)
    return _page(
        "Workspace connected",
        f"Connected as {admin.email} ({admin.hosted_domain}). "
        "Your first discovery scan can start now — close this tab.",
    )


@router.post("/google/{tenant_id}/test")
async def test_google_connection(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Is this tenant's connection still alive? Used by the dashboard banner."""
    creds = await context.repo.load_credentials(
        tenant_id,
        Provider.GOOGLE,
        client_id=context.settings.google_client_id,
        client_secret=context.settings.google_client_secret,
    )
    if creds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google connection for this tenant")
    try:
        connector = GoogleWorkspaceConnector(creds, concurrency=1, max_users=1)
        return await _to_thread(connector.test_connection)
    except AuthError as exc:
        await context.repo.mark_credentials_broken(tenant_id, Provider.GOOGLE, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


async def _to_thread(fn, *args):
    """The Google client is synchronous; keep it off the event loop."""
    return await asyncio.to_thread(fn, *args)


def _page(title: str, message: str) -> HTMLResponse:
    """A plain confirmation page. The admin lands here in a browser, not curl."""
    safe_title = _escape(title)
    safe_message = _escape(message)
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>{safe_title}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:34rem;margin:15vh auto;
padding:0 1.5rem;color:#111}}h1{{font-size:1.4rem}}p{{color:#444}}</style></head>
<body><h1>{safe_title}</h1><p>{safe_message}</p></body></html>"""
    )


def _escape(text: str) -> str:
    return html.escape(text, quote=True)
