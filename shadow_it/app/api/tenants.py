"""Tenant CRUD and API-key issuance (platform-operator endpoints)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from .deps import AppContext, get_context, require_admin, require_tenant

router = APIRouter(prefix="/v1", tags=["tenants"])


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    primary_domain: str = Field(min_length=3, max_length=253)
    contact_email: EmailStr | None = None
    plan: str = "trial"


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    _: str = Depends(require_admin),
    context: AppContext = Depends(get_context),
) -> dict:
    """Create a customer and mint its first API key.

    The raw key is returned exactly once — only its hash is stored, so a lost
    key is reissued, never recovered.
    """
    tenant = await context.repo.create_tenant(
        name=body.name,
        primary_domain=body.primary_domain.lower().strip(),
        contact_email=str(body.contact_email or ""),
        plan=body.plan,
    )
    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    await context.repo.create_api_key(str(tenant["id"]), raw_key)
    return {
        "tenant": {**tenant, "id": str(tenant["id"])},
        "api_key": raw_key,
        "warning": "Store this key now — it is not recoverable.",
    }


@router.get("/tenants")
async def list_tenants(
    _: str = Depends(require_admin),
    context: AppContext = Depends(get_context),
) -> dict:
    tenants = await context.repo.list_tenants(active_only=False)
    return {"tenants": [{**t, "id": str(t["id"])} for t in tenants]}


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    tenant = await context.repo.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return {**tenant, "id": str(tenant["id"])}


class PolicyRule(BaseModel):
    kind: str = Field(pattern="^(allowlist_client|blocklist_client|allowlist_keyword)$")
    value: str = Field(min_length=1, max_length=500)
    note: str = ""


@router.post("/tenants/{tenant_id}/policy")
async def add_policy_rule(
    body: PolicyRule,
    tenant_id: str = Depends(require_tenant),
    context: AppContext = Depends(get_context),
) -> dict:
    """Allowlist a sanctioned app, or blocklist one you have banned.

    Rules apply at the *next* scan's scoring pass, which keeps historical
    scores explainable instead of silently rewriting them.
    """
    await context.repo.add_policy_rule(tenant_id, body.kind, body.value, body.note)
    return {"ok": True, "kind": body.kind, "value": body.value}
