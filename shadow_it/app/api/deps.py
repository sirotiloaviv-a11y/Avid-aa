"""Shared request-scoped plumbing: app context and authentication."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Path, Request, status

from ..config import Settings
from ..crypto import SecretBox, constant_time_equals
from ..db import Database
from ..services import Repository, ScanService


@dataclass
class AppContext:
    """Built once at startup and hung off ``app.state``."""

    settings: Settings
    db: Database
    repo: Repository
    scans: ScanService
    secrets: SecretBox


def get_context(request: Request) -> AppContext:
    context = getattr(request.app.state, "context", None)
    if context is None:  # only reachable if startup failed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service is not ready")
    return context


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


async def require_admin(
    authorization: str | None = Header(default=None),
    context: AppContext = Depends(get_context),
) -> str:
    """Platform-operator access: onboarding, tenant creation, cross-tenant reads."""
    token = _bearer(authorization)
    if not constant_time_equals(token, context.settings.api_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid API key")
    return token


async def require_tenant(
    tenant_id: str = Path(...),
    authorization: str | None = Header(default=None),
    context: AppContext = Depends(get_context),
) -> str:
    """Authorize the caller *for this tenant*, and return the tenant id.

    Two callers are accepted: the platform operator key, and a tenant's own
    API key. A tenant key is only ever valid for the tenant it belongs to —
    this check is the whole tenant-isolation boundary on the read path, so it
    stays boring, explicit, and in one place.
    """
    token = _bearer(authorization)

    if constant_time_equals(token, context.settings.api_key):
        return tenant_id

    owner = await context.repo.tenant_for_api_key(token)
    if owner is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid API key")
    if owner != tenant_id:
        # Deliberately the same error as an unknown key: a distinct message
        # would confirm that this tenant id exists.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid API key")
    return tenant_id
