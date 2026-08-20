"""All SQL lives here.

Every method takes a tenant_id and every query filters on it. That repetition
is the point: there is no code path in this product that can read another
customer's inventory by forgetting a WHERE clause somewhere else.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

import asyncpg

from ..crypto import SecretBox, hash_api_key
from ..models import AppGrant, DirectoryUser, DiscoveredApp, Provider, RiskAssessment
from ..connectors.base import TenantCredentials
from ..risk.engine import RiskPolicy

log = logging.getLogger(__name__)


class Repository:
    def __init__(self, pool: asyncpg.Pool, secrets: SecretBox):
        self._pool = pool
        self._secrets = secrets

    # ------------------------------------------------------------ tenants
    async def create_tenant(
        self, name: str, primary_domain: str, contact_email: str = "", plan: str = "trial"
    ) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO tenants (name, primary_domain, contact_email, plan)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (lower(primary_domain)) DO UPDATE
                SET name = EXCLUDED.name,
                    contact_email = EXCLUDED.contact_email
            RETURNING id, name, primary_domain, contact_email, plan, is_active,
                      directory_size, created_at
            """,
            name, primary_domain, contact_email, plan,
        )
        return dict(row)

    async def get_tenant(self, tenant_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, name, primary_domain, contact_email, plan, is_active,
                   directory_size, settings, created_at
              FROM tenants WHERE id = $1
            """,
            tenant_id,
        )
        return dict(row) if row else None

    async def list_tenants(self, active_only: bool = True) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT id, name, primary_domain, plan, is_active, directory_size, created_at
              FROM tenants
             WHERE ($1 IS FALSE OR is_active)
             ORDER BY created_at
            """,
            active_only,
        )
        return [dict(r) for r in rows]

    async def set_directory_size(self, tenant_id: str, size: int) -> None:
        await self._pool.execute(
            "UPDATE tenants SET directory_size = $2 WHERE id = $1", tenant_id, size
        )

    # -------------------------------------------------------- credentials
    async def save_credentials(
        self,
        tenant_id: str,
        provider: Provider,
        admin_email: str,
        secret: str,
        method: str = "oauth_refresh_token",
        granted_scopes: Iterable[str] = (),
        customer_id: str = "my_customer",
    ) -> str:
        """Encrypt and store. ``secret`` is a refresh token or SA key JSON.

        Reconnecting retires the previous credential rather than deleting it,
        so an audit can still answer "whose token were we using in March?".
        """
        ciphertext = self._secrets.encrypt(secret)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE tenant_credentials SET status = 'revoked'
                     WHERE tenant_id = $1 AND provider = $2 AND status = 'active'
                    """,
                    tenant_id, provider.value,
                )
                credential_id = await conn.fetchval(
                    """
                    INSERT INTO tenant_credentials
                        (tenant_id, provider, method, admin_email, customer_id,
                         secret_ciphertext, key_id, granted_scopes, status,
                         last_verified_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', now())
                    RETURNING id
                    """,
                    tenant_id, provider.value, method, admin_email, customer_id,
                    ciphertext, self._secrets.key_id, list(granted_scopes),
                )
        log.info("Stored %s credentials for tenant %s", provider.value, tenant_id)
        return str(credential_id)

    async def load_credentials(
        self, tenant_id: str, provider: Provider, client_id: str = "", client_secret: str = ""
    ) -> TenantCredentials | None:
        """Decrypt the active credential. The only decryption site in the app."""
        row = await self._pool.fetchrow(
            """
            SELECT method, admin_email, customer_id, secret_ciphertext
              FROM tenant_credentials
             WHERE tenant_id = $1 AND provider = $2 AND status = 'active'
             LIMIT 1
            """,
            tenant_id, provider.value,
        )
        if row is None:
            return None

        secret = self._secrets.decrypt(row["secret_ciphertext"])
        if row["method"] == "service_account":
            return TenantCredentials(
                provider=provider,
                admin_email=row["admin_email"],
                service_account_info=json.loads(secret),
                customer_id=row["customer_id"],
            )
        return TenantCredentials(
            provider=provider,
            admin_email=row["admin_email"],
            refresh_token=secret,
            client_id=client_id,
            client_secret=client_secret,
            customer_id=row["customer_id"],
        )

    async def mark_credentials_broken(
        self, tenant_id: str, provider: Provider, error: str
    ) -> None:
        """Called when the provider rejects our token — the tenant must reconnect."""
        await self._pool.execute(
            """
            UPDATE tenant_credentials
               SET status = 'expired', last_error = $3
             WHERE tenant_id = $1 AND provider = $2 AND status = 'active'
            """,
            tenant_id, provider.value, error[:500],
        )

    # ------------------------------------------------------------ api keys
    async def tenant_for_api_key(self, raw_key: str) -> str | None:
        row = await self._pool.fetchrow(
            """
            UPDATE api_keys SET last_used_at = now()
             WHERE key_hash = $1 AND revoked_at IS NULL
            RETURNING tenant_id
            """,
            hash_api_key(raw_key),
        )
        return str(row["tenant_id"]) if row else None

    async def create_api_key(self, tenant_id: str, raw_key: str, name: str = "default") -> str:
        key_id = await self._pool.fetchval(
            """
            INSERT INTO api_keys (tenant_id, name, key_hash, key_prefix)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            tenant_id, name, hash_api_key(raw_key), raw_key[:8],
        )
        return str(key_id)

    # ------------------------------------------------------------- users
    async def upsert_users(
        self, tenant_id: str, users: list[DirectoryUser], provider: Provider = Provider.GOOGLE
    ) -> dict[str, str]:
        """Store the directory and return {email: user row id}."""
        if not users:
            return {}
        records = [
            (tenant_id, provider.value, u.external_id, u.email, u.full_name,
             u.is_admin, u.is_suspended, u.org_unit)
            for u in users
        ]
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO directory_users
                        (tenant_id, provider, external_id, email, full_name,
                         is_admin, is_suspended, org_unit)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (tenant_id, provider, lower(email)) DO UPDATE
                        SET full_name    = EXCLUDED.full_name,
                            is_admin     = EXCLUDED.is_admin,
                            is_suspended = EXCLUDED.is_suspended,
                            org_unit     = EXCLUDED.org_unit,
                            last_seen_at = now()
                    """,
                    records,
                )
            rows = await conn.fetch(
                "SELECT id, email FROM directory_users WHERE tenant_id = $1 AND provider = $2",
                tenant_id, provider.value,
            )
        return {r["email"].lower(): str(r["id"]) for r in rows}

    # -------------------------------------------------------------- scans
    async def start_scan(
        self, tenant_id: str, provider: Provider, trigger_kind: str = "manual"
    ) -> str:
        scan_id = await self._pool.fetchval(
            """
            INSERT INTO scans (tenant_id, provider, trigger_kind, status)
            VALUES ($1, $2, $3, 'running')
            RETURNING id
            """,
            tenant_id, provider.value, trigger_kind,
        )
        return str(scan_id)

    async def finish_scan(
        self,
        scan_id: str,
        status: str,
        users_scanned: int = 0,
        grants_found: int = 0,
        apps_found: int = 0,
        new_apps: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE scans
               SET status = $2, users_scanned = $3, grants_found = $4,
                   apps_found = $5, new_apps = $6, errors = $7::jsonb,
                   finished_at = now()
             WHERE id = $1
            """,
            scan_id, status, users_scanned, grants_found, apps_found, new_apps,
            json.dumps(errors or []),
        )

    async def latest_scan(self, tenant_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, status, trigger_kind, users_scanned, grants_found, apps_found,
                   new_apps, errors, started_at, finished_at
              FROM scans WHERE tenant_id = $1
             ORDER BY started_at DESC LIMIT 1
            """,
            tenant_id,
        )
        return dict(row) if row else None

    # --------------------------------------------------------------- apps
    async def upsert_app(
        self,
        tenant_id: str,
        app: DiscoveredApp,
        assessment: RiskAssessment,
        scan_id: str,
    ) -> dict:
        """Insert or refresh one app, and record what changed since last scan.

        Read-then-write instead of a bare upsert: the diff (new app, widened
        scopes, risk climbed) is the alerting product, and it is only visible
        while we still hold the previous row.
        """
        scopes = sorted(app.scopes)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                previous = await conn.fetchrow(
                    """
                    SELECT id, scopes, risk_score, risk_band, user_count, status
                      FROM discovered_apps
                     WHERE tenant_id = $1 AND provider = $2 AND client_id = $3
                     FOR UPDATE
                    """,
                    tenant_id, app.provider.value, app.client_id,
                )

                app_id = await conn.fetchval(
                    """
                    INSERT INTO discovered_apps
                        (tenant_id, provider, client_id, display_name, is_anonymous,
                         is_native_app, category, scopes, user_count, admin_count,
                         risk_score, risk_band, risk_reasons, capabilities)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13::jsonb, $14::jsonb)
                    ON CONFLICT (tenant_id, provider, client_id) DO UPDATE
                        SET display_name  = EXCLUDED.display_name,
                            is_anonymous  = EXCLUDED.is_anonymous,
                            is_native_app = EXCLUDED.is_native_app,
                            category      = EXCLUDED.category,
                            scopes        = EXCLUDED.scopes,
                            user_count    = EXCLUDED.user_count,
                            admin_count   = EXCLUDED.admin_count,
                            risk_score    = EXCLUDED.risk_score,
                            risk_band     = EXCLUDED.risk_band,
                            risk_reasons  = EXCLUDED.risk_reasons,
                            capabilities  = EXCLUDED.capabilities,
                            last_seen_at  = now()
                    RETURNING id
                    """,
                    tenant_id, app.provider.value, app.client_id, app.display_name,
                    app.is_anonymous, app.is_native_app, assessment.category, scopes,
                    app.install_count, len(app.admin_user_emails), assessment.score,
                    assessment.band.value, json.dumps(assessment.reasons),
                    json.dumps(assessment.capabilities),
                )
                app_id = str(app_id)

                events = _diff_events(previous, app, assessment, scopes)
                for kind, summary, detail in events:
                    await conn.execute(
                        """
                        INSERT INTO app_events (tenant_id, app_id, scan_id, kind, summary, detail)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """,
                        tenant_id, app_id, scan_id, kind, summary, json.dumps(detail),
                    )

        return {"app_id": app_id, "is_new": previous is None, "events": len(events)}

    async def upsert_grants(
        self,
        tenant_id: str,
        app_id: str,
        grants: list[AppGrant],
        user_ids: dict[str, str],
    ) -> None:
        if not grants:
            return
        records = [
            (tenant_id, app_id, user_ids.get(g.user_email.lower()), g.user_email, sorted(g.scopes))
            for g in grants
        ]
        await self._pool.executemany(
            """
            INSERT INTO app_grants (tenant_id, app_id, user_id, user_email, scopes)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_id, app_id, lower(user_email)) DO UPDATE
                SET scopes = EXCLUDED.scopes,
                    user_id = COALESCE(EXCLUDED.user_id, app_grants.user_id),
                    last_seen_at = now(),
                    revoked_at = NULL
            """,
            records,
        )

    async def mark_stale_grants_revoked(self, tenant_id: str, scan_started_at: datetime) -> int:
        """A grant this scan did not see is a grant the user revoked.

        Recorded rather than deleted: "who removed what, when" is half of what
        a customer wants from an audit trail.
        """
        return int(
            (
                await self._pool.execute(
                    """
                    UPDATE app_grants
                       SET revoked_at = now()
                     WHERE tenant_id = $1 AND revoked_at IS NULL AND last_seen_at < $2
                    """,
                    tenant_id, scan_started_at,
                )
            ).split()[-1]
        )

    async def list_apps(
        self,
        tenant_id: str,
        band: str | None = None,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT id, client_id, display_name, category, risk_score, risk_band,
                   risk_reasons, capabilities, scopes, user_count, admin_count,
                   is_anonymous, is_native_app, status, first_seen_at, last_seen_at
              FROM discovered_apps
             WHERE tenant_id = $1
               AND ($2::risk_band  IS NULL OR risk_band = $2::risk_band)
               AND ($3::app_status IS NULL OR status = $3::app_status)
               AND ($4::text       IS NULL OR category = $4)
               AND ($5::text       IS NULL OR display_name ILIKE '%' || $5 || '%')
             ORDER BY risk_score DESC, display_name
             LIMIT $6 OFFSET $7
            """,
            tenant_id, band, status, category, search, limit, offset,
        )
        return [dict(r) for r in rows]

    async def get_app(self, tenant_id: str, app_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT a.*,
                   COALESCE(
                       (SELECT json_agg(json_build_object(
                            'user_email', g.user_email,
                            'scopes', g.scopes,
                            'first_seen_at', g.first_seen_at,
                            'revoked_at', g.revoked_at))
                          FROM app_grants g
                         WHERE g.app_id = a.id AND g.tenant_id = a.tenant_id),
                       '[]'::json) AS grants
              FROM discovered_apps a
             WHERE a.tenant_id = $1 AND a.id = $2
            """,
            tenant_id, app_id,
        )
        return dict(row) if row else None

    async def set_app_status(
        self, tenant_id: str, app_id: str, status: str, reviewer: str = ""
    ) -> bool:
        result = await self._pool.execute(
            """
            UPDATE discovered_apps
               SET status = $3::app_status, reviewed_by = $4, reviewed_at = now()
             WHERE tenant_id = $1 AND id = $2
            """,
            tenant_id, app_id, status, reviewer,
        )
        return result.endswith("1")

    async def inventory_summary(self, tenant_id: str) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT COUNT(*)                                            AS total_apps,
                   COUNT(*) FILTER (WHERE risk_band = 'high')          AS high,
                   COUNT(*) FILTER (WHERE risk_band = 'medium')        AS medium,
                   COUNT(*) FILTER (WHERE risk_band = 'low')           AS low,
                   COUNT(*) FILTER (WHERE status = 'new')              AS unreviewed,
                   COUNT(*) FILTER (WHERE is_anonymous)                AS unverified_publisher
              FROM discovered_apps WHERE tenant_id = $1
            """,
            tenant_id,
        )
        return dict(row) if row else {}

    async def recent_events(self, tenant_id: str, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT e.id, e.kind, e.summary, e.detail, e.created_at,
                   a.display_name, a.client_id, a.risk_band
              FROM app_events e
              LEFT JOIN discovered_apps a ON a.id = e.app_id
             WHERE e.tenant_id = $1
             ORDER BY e.created_at DESC
             LIMIT $2
            """,
            tenant_id, limit,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- policy
    async def load_policy(self, tenant_id: str) -> RiskPolicy:
        rows = await self._pool.fetch(
            "SELECT kind, value FROM policy_rules WHERE tenant_id = $1", tenant_id
        )
        size = await self._pool.fetchval(
            "SELECT directory_size FROM tenants WHERE id = $1", tenant_id
        )
        policy = RiskPolicy(directory_size=int(size or 0))
        for row in rows:
            if row["kind"] == "allowlist_client":
                policy.allowlisted_client_ids.add(row["value"])
            elif row["kind"] == "blocklist_client":
                policy.blocklisted_client_ids.add(row["value"])
            elif row["kind"] == "allowlist_keyword":
                policy.allowlisted_keywords.add(row["value"])
        return policy

    async def add_policy_rule(
        self, tenant_id: str, kind: str, value: str, note: str = "", created_by: str = ""
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO policy_rules (tenant_id, kind, value, note, created_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_id, kind, lower(value)) DO UPDATE SET note = EXCLUDED.note
            """,
            tenant_id, kind, value, note, created_by,
        )


def _diff_events(
    previous: asyncpg.Record | None,
    app: DiscoveredApp,
    assessment: RiskAssessment,
    scopes: list[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    """What changed about this app since the last scan.

    These rows are what a daily digest email is built from — the inventory is
    the report, the diff is the alert.
    """
    now = datetime.now(timezone.utc).isoformat()
    if previous is None:
        return [(
            "app_discovered",
            f"New app discovered: {app.display_name} ({assessment.band.value} risk)",
            {"score": assessment.score, "users": app.install_count, "at": now},
        )]

    events: list[tuple[str, str, dict[str, Any]]] = []
    added_scopes = sorted(set(scopes) - set(previous["scopes"] or []))
    if added_scopes:
        events.append((
            "scope_expanded",
            f"{app.display_name} gained {len(added_scopes)} new scope(s)",
            {"added_scopes": added_scopes},
        ))
    if assessment.score > int(previous["risk_score"]):
        events.append((
            "risk_increased",
            f"{app.display_name} risk rose {previous['risk_score']} -> {assessment.score}",
            {"from": int(previous["risk_score"]), "to": assessment.score,
             "band": assessment.band.value},
        ))
    added_users = app.install_count - int(previous["user_count"])
    if added_users > 0:
        events.append((
            "user_added",
            f"{app.display_name} authorized by {added_users} more user(s)",
            {"total_users": app.install_count},
        ))
    return events
