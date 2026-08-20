"""Provider connection endpoints — the customer-facing onboarding path.

Two providers, two very different consent models:

* **Google** — three-legged OAuth. The admin authorizes, we get a refresh token
  scoped to that admin, and we store it (encrypted). Losing the admin loses the
  connection.
* **Microsoft** — admin consent to a multi-tenant app registration. There is no
  code exchange and no per-customer token: the redirect just names the tenant
  that consented, and from then on we mint app-only tokens with our own client
  credentials. The stored value is a public GUID.

Both share the signed-state machinery in ``oauth_state.py``, because
both callbacks are unauthenticated by necessity.
"""

from __future__ import annotations

import asyncio
import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from ..connectors import build_connector, close_connector
from ..connectors.microsoft365 import REQUIRED_APP_ROLES
from ..connectors.base import AuthError, ConnectorError, TenantCredentials
from ..models import Provider
from ..services import google_oauth, microsoft_oauth
from ..oauth_state import OAuthError, make_state
from .deps import AppContext, get_context, require_tenant

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/connect", tags=["connect"])

GOOGLE_CALLBACK_PATH = "/v1/connect/google/callback"
MICROSOFT_CALLBACK_PATH = "/v1/connect/microsoft/callback"


def _redirect_uri(context: AppContext, path: str) -> str:
    return f"{context.settings.public_base_url}{path}"


def _require_provider_configured(context: AppContext, provider: Provider) -> None:
    if provider.value not in context.settings.enabled_providers:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            f"{provider.value} is not configured on this deployment "
            f"(set {provider.value.upper()}_CLIENT_ID and _CLIENT_SECRET).",
        )


@router.get("/providers")
async def list_providers(context: AppContext = Depends(get_context)) -> dict:
    """Which providers this deployment can onboard. Drives the connect screen."""
    return {"providers": context.settings.enabled_providers}


# ================================================================= google ===
# Path is /google/start/{tenant_id} rather than /google/{tenant_id} so that a
# tenant id can never shadow the fixed /google/callback route.
@router.get("/google/start/{tenant_id}")
async def start_google_connect(
    tenant_id: str = Depends(require_tenant),
    login_hint: str = Query("", description="Pre-fill the admin's email"),
    context: AppContext = Depends(get_context),
) -> dict:
    """Build the consent URL for the customer's Workspace super-admin."""
    _require_provider_configured(context, Provider.GOOGLE)
    if await context.repo.get_tenant(tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    state = make_state(tenant_id, context.settings.api_key)
    url = google_oauth.build_authorize_url(
        client_id=context.settings.google_client_id,
        redirect_uri=_redirect_uri(context, GOOGLE_CALLBACK_PATH),
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
            redirect_uri=_redirect_uri(context, GOOGLE_CALLBACK_PATH),
        )
    except OAuthError as exc:
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
        await _probe(probe, context)
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
    return await _test_connection(tenant_id, Provider.GOOGLE, context)


# ============================================================== microsoft ===
@router.get("/microsoft/start/{tenant_id}")
async def start_microsoft_connect(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Build the admin-consent URL for the customer's Global Administrator.

    Only a Global Administrator can grant directory-wide application
    permissions; anyone else lands on an access_denied redirect, which the
    callback turns into that sentence rather than a stack trace.
    """
    _require_provider_configured(context, Provider.MICROSOFT)
    if await context.repo.get_tenant(tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    state = make_state(tenant_id, context.settings.api_key)
    url = microsoft_oauth.build_admin_consent_url(
        client_id=context.settings.microsoft_client_id,
        redirect_uri=_redirect_uri(context, MICROSOFT_CALLBACK_PATH),
        state=state,
    )
    return {
        "authorize_url": url,
        "expires_in": microsoft_oauth.STATE_TTL_SECONDS,
        "required_permissions": list(REQUIRED_APP_ROLES),
        "requires_role": "Global Administrator",
    }


@router.get("/microsoft/callback", include_in_schema=False)
async def microsoft_callback(
    tenant: str = Query(default=""),
    state: str = Query(default=""),
    admin_consent: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
    context: AppContext = Depends(get_context),
):
    """Entra redirects the admin back here after the consent decision.

    No code exchange: the useful payload is ``tenant``, the directory id that
    consented. It is validated as a GUID before it is ever interpolated into a
    token URL.
    """
    try:
        our_tenant_id, consented = microsoft_oauth.parse_callback(
            tenant=tenant,
            state=state,
            admin_consent=admin_consent,
            error=error,
            error_description=error_description,
            secret=context.settings.api_key,
        )
    except OAuthError as exc:
        log.warning("Microsoft connect failed: %s", exc)
        return _page("Connection failed", str(exc))

    # Two-step probe: first that Entra will issue us an app-only token for this
    # directory at all (the service principal propagates asynchronously, so this
    # retries), then that the token actually carries the permissions we need.
    try:
        await microsoft_oauth.verify_app_only_access(
            tenant_id=consented.tenant_id,
            client_id=context.settings.microsoft_client_id,
            client_secret=context.settings.microsoft_client_secret,
        )
    except OAuthError as exc:
        return _page("Connection failed", str(exc))

    probe = TenantCredentials(
        provider=Provider.MICROSOFT,
        directory_tenant_id=consented.tenant_id,
        client_id=context.settings.microsoft_client_id,
        client_secret=context.settings.microsoft_client_secret,
    )
    try:
        result = await _probe(probe, context)
    except (AuthError, ConnectorError) as exc:
        return _page("Connection failed", str(exc))

    await context.repo.save_credentials(
        tenant_id=our_tenant_id,
        provider=Provider.MICROSOFT,
        # Entra's admin-consent redirect does not identify the admin who
        # clicked, so there is no email to record here — the directory id is
        # the whole identity.
        admin_email="",
        secret=consented.tenant_id,
        method="client_credentials",
        granted_scopes=REQUIRED_APP_ROLES,
    )
    organization = result.get("organization") or consented.tenant_id
    log.info("Tenant %s connected Microsoft 365 directory %s", our_tenant_id, consented.tenant_id)
    return _page(
        "Microsoft 365 connected",
        f"Connected to {organization}. Your first discovery scan can start now "
        "— close this tab.",
    )


@router.post("/microsoft/{tenant_id}/test")
async def test_microsoft_connection(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    return await _test_connection(tenant_id, Provider.MICROSOFT, context)


# ================================================================= shared ===
async def _test_connection(tenant_id: str, provider: Provider, context: AppContext) -> dict:
    """Is this tenant's connection still alive? Used by the dashboard banner."""
    client_id, client_secret = context.settings.oauth_client(provider.value)
    creds = await context.repo.load_credentials(
        tenant_id, provider, client_id=client_id, client_secret=client_secret
    )
    if creds is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No {provider.value} connection for this tenant"
        )
    try:
        return await _probe(creds, context)
    except AuthError as exc:
        await context.repo.mark_credentials_broken(tenant_id, provider, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


async def _probe(credentials: TenantCredentials, context: AppContext) -> dict:
    """Cheapest call that proves the credentials work, off the event loop."""
    connector = build_connector(credentials, context.settings, concurrency=1, max_users=1)
    try:
        return await asyncio.to_thread(connector.test_connection)
    finally:
        close_connector(connector)


def _page(title: str, message: str) -> HTMLResponse:
    """A plain confirmation page. The admin lands here in a browser, not curl."""
    safe_title = html.escape(title, quote=True)
    safe_message = html.escape(message, quote=True)
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>{safe_title}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:34rem;margin:15vh auto;
padding:0 1.5rem;color:#111}}h1{{font-size:1.4rem}}p{{color:#444}}</style></head>
<body><h1>{safe_title}</h1><p>{safe_message}</p></body></html>"""
    )
