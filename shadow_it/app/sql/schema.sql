-- Shadow IT Discovery — PostgreSQL schema (requires PostgreSQL 13+ for
-- gen_random_uuid()).
--
-- Applied by app/db.py on boot inside a transaction. It is written to be
-- idempotent, so re-running it on an existing database is a no-op and a fresh
-- deploy needs no migration tool. When the product outgrows that, the first
-- Alembic revision is this file.
--
-- Two rules govern everything below:
--   1. Every row that belongs to a customer carries tenant_id, and every query
--      filters on it. Multi-tenant leakage is the one bug this product cannot
--      survive.
--   2. Secrets are stored encrypted (bytea ciphertext from app/crypto.py),
--      never as text. The database is assumed to be readable by a future
--      attacker; the encryption key lives only in the process environment.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------- enums ----
-- Each CREATE TYPE gets its own exception scope: sharing one block means a
-- half-applied schema silently skips every type after the first existing one.
DO $$ BEGIN
    CREATE TYPE provider_kind AS ENUM ('google', 'microsoft');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE risk_band AS ENUM ('low', 'medium', 'high');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE app_status AS ENUM ('new', 'approved', 'blocked', 'ignored');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE scan_status AS ENUM ('running', 'success', 'partial', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE auth_method AS ENUM ('oauth_refresh_token', 'service_account',
                                    'client_credentials');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE credential_status AS ENUM ('active', 'expired', 'revoked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ------------------------------------------------------------- tenants ----
-- One row per customer company.
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,
    primary_domain  TEXT        NOT NULL,
    contact_email   TEXT        NOT NULL DEFAULT '',
    plan            TEXT        NOT NULL DEFAULT 'trial',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    -- Directory size at last scan; the risk engine needs it to read "12 users"
    -- as a share of the company rather than an absolute number.
    directory_size  INTEGER     NOT NULL DEFAULT 0,
    settings        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS tenants_primary_domain_key
    ON tenants (lower(primary_domain));

-- ------------------------------------------------------------ api keys ----
-- Dashboard/API authentication. Only the hash is stored: a database dump must
-- not hand over working keys.
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL DEFAULT 'default',
    key_hash     TEXT        NOT NULL UNIQUE,   -- sha256 of the raw key
    key_prefix   TEXT        NOT NULL DEFAULT '', -- first 8 chars, for display
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON api_keys (tenant_id)
    WHERE revoked_at IS NULL;

-- -------------------------------------------------------- credentials -----
-- The admin credentials we hold on the customer's behalf. The highest-value
-- rows in the system: encrypted at rest, redacted in every API response, and
-- never written to a log.
CREATE TABLE IF NOT EXISTS tenant_credentials (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider           provider_kind NOT NULL,
    method             auth_method   NOT NULL DEFAULT 'oauth_refresh_token',
    -- The admin who consented (OAuth) or is impersonated (service account).
    admin_email        TEXT          NOT NULL,
    customer_id        TEXT          NOT NULL DEFAULT 'my_customer',
    -- Fernet ciphertext of the refresh token or service-account JSON.
    secret_ciphertext  BYTEA         NOT NULL,
    -- Fingerprint of the key that encrypted it, so rotation can find stragglers.
    key_id             TEXT          NOT NULL DEFAULT '',
    granted_scopes     TEXT[]        NOT NULL DEFAULT '{}',
    status             credential_status NOT NULL DEFAULT 'active',
    last_error         TEXT          NOT NULL DEFAULT '',
    last_verified_at   TIMESTAMPTZ,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- One live credential per tenant+provider; reconnecting replaces it.
CREATE UNIQUE INDEX IF NOT EXISTS tenant_credentials_active_key
    ON tenant_credentials (tenant_id, provider)
    WHERE status = 'active';

-- --------------------------------------------------- directory users ------
CREATE TABLE IF NOT EXISTS directory_users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider     provider_kind NOT NULL DEFAULT 'google',
    external_id  TEXT          NOT NULL,
    email        TEXT          NOT NULL,
    full_name    TEXT          NOT NULL DEFAULT '',
    is_admin     BOOLEAN       NOT NULL DEFAULT FALSE,
    is_suspended BOOLEAN       NOT NULL DEFAULT FALSE,
    org_unit     TEXT          NOT NULL DEFAULT '',
    first_seen_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS directory_users_tenant_email_key
    ON directory_users (tenant_id, provider, lower(email));
CREATE INDEX IF NOT EXISTS directory_users_admins_idx
    ON directory_users (tenant_id) WHERE is_admin;

-- ------------------------------------------------- discovered apps --------
-- One row per third-party client id per tenant: the unit a human reviews.
CREATE TABLE IF NOT EXISTS discovered_apps (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider       provider_kind NOT NULL DEFAULT 'google',
    client_id      TEXT          NOT NULL,
    display_name   TEXT          NOT NULL DEFAULT '',
    -- Google's "anonymous": the client is not registered to any verified
    -- project, so no publisher can be identified. Strongest Shadow IT signal.
    -- Google: the client is registered to no verified project.
    -- Microsoft: the service principal has no verified publisher.
    -- Same question either way: can anyone vouch for this publisher?
    is_anonymous   BOOLEAN       NOT NULL DEFAULT FALSE,
    is_native_app  BOOLEAN       NOT NULL DEFAULT FALSE,
    -- Entra only. An admin consented for the whole directory, and/or the app
    -- holds app-only permissions that work with no user signed in.
    tenant_wide_consent        BOOLEAN NOT NULL DEFAULT FALSE,
    has_application_permissions BOOLEAN NOT NULL DEFAULT FALSE,
    category       TEXT          NOT NULL DEFAULT 'unknown',
    scopes         TEXT[]        NOT NULL DEFAULT '{}',
    user_count     INTEGER       NOT NULL DEFAULT 0,
    admin_count    INTEGER       NOT NULL DEFAULT 0,
    risk_score     INTEGER       NOT NULL DEFAULT 0,
    risk_band      risk_band     NOT NULL DEFAULT 'low',
    -- Why the score is what it is. Rendered verbatim in the UI, so a customer
    -- can audit a finding without asking us.
    risk_reasons   JSONB         NOT NULL DEFAULT '[]'::jsonb,
    capabilities   JSONB         NOT NULL DEFAULT '[]'::jsonb,
    status         app_status    NOT NULL DEFAULT 'new',
    reviewed_by    TEXT          NOT NULL DEFAULT '',
    reviewed_at    TIMESTAMPTZ,
    first_seen_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    last_seen_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS discovered_apps_tenant_client_key
    ON discovered_apps (tenant_id, provider, client_id);
-- The dashboard's default view: this tenant's unreviewed apps, worst first.
CREATE INDEX IF NOT EXISTS discovered_apps_triage_idx
    ON discovered_apps (tenant_id, risk_score DESC)
    WHERE status = 'new';
CREATE INDEX IF NOT EXISTS discovered_apps_band_idx
    ON discovered_apps (tenant_id, risk_band);

-- ------------------------------------------------------- app grants -------
-- The atomic fact: user X authorized app Y with scopes Z. Kept per user so
-- "who installed this?" and offboarding checks are one query.
CREATE TABLE IF NOT EXISTS app_grants (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    app_id        UUID        NOT NULL REFERENCES discovered_apps(id) ON DELETE CASCADE,
    user_id       UUID        REFERENCES directory_users(id) ON DELETE SET NULL,
    -- A real principal, or one of the synthetic Entra ones:
    -- "(all users — admin consent)" / "(application — no user)".
    user_email    TEXT        NOT NULL,
    grant_type    TEXT        NOT NULL DEFAULT 'delegated', -- delegated |
                                                            -- tenant_wide |
                                                            -- application
    scopes        TEXT[]      NOT NULL DEFAULT '{}',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set when a scan no longer sees the grant (user revoked it, or we did).
    revoked_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS app_grants_unique_key
    ON app_grants (tenant_id, app_id, lower(user_email));
CREATE INDEX IF NOT EXISTS app_grants_user_idx
    ON app_grants (tenant_id, lower(user_email)) WHERE revoked_at IS NULL;

-- ----------------------------------------------------------- scans --------
CREATE TABLE IF NOT EXISTS scans (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider       provider_kind NOT NULL DEFAULT 'google',
    status         scan_status   NOT NULL DEFAULT 'running',
    trigger_kind   TEXT          NOT NULL DEFAULT 'manual', -- manual | scheduled
    users_scanned  INTEGER       NOT NULL DEFAULT 0,
    grants_found   INTEGER       NOT NULL DEFAULT 0,
    apps_found     INTEGER       NOT NULL DEFAULT 0,
    new_apps       INTEGER       NOT NULL DEFAULT 0,
    errors         JSONB         NOT NULL DEFAULT '[]'::jsonb,
    started_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS scans_tenant_started_idx
    ON scans (tenant_id, started_at DESC);

-- ---------------------------------------------------------- events --------
-- The change feed. "New high-risk app appeared" and "an app quietly gained
-- Drive access" are the alerts customers actually pay for, and both are
-- diffs rather than states — so they need their own history.
CREATE TABLE IF NOT EXISTS app_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    app_id      UUID        REFERENCES discovered_apps(id) ON DELETE CASCADE,
    scan_id     UUID        REFERENCES scans(id) ON DELETE SET NULL,
    kind        TEXT        NOT NULL, -- app_discovered | scope_expanded |
                                      -- user_added | risk_increased | grant_revoked
    summary     TEXT        NOT NULL DEFAULT '',
    detail      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    notified_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS app_events_tenant_created_idx
    ON app_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS app_events_unsent_idx
    ON app_events (tenant_id) WHERE notified_at IS NULL;

-- ----------------------------------------------------------- policy -------
-- Customer-editable scoring overrides, read into risk.RiskPolicy per scan.
CREATE TABLE IF NOT EXISTS policy_rules (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind       TEXT        NOT NULL, -- allowlist_client | blocklist_client | allowlist_keyword
    value      TEXT        NOT NULL,
    note       TEXT        NOT NULL DEFAULT '',
    created_by TEXT        NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS policy_rules_unique_key
    ON policy_rules (tenant_id, kind, lower(value));

-- ------------------------------------------------------- updated_at -------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['tenants', 'tenant_credentials', 'discovered_apps'] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON %I', t || '_touch_updated_at', t
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
            t || '_touch_updated_at', t
        );
    END LOOP;
END $$;

-- ------------------------------------------------------- migrations -------
-- Bring a v1 database up to v2 (the Microsoft 365 connector). Additive only,
-- so it is safe to run against a fresh database that already has these.
--
-- ALTER TYPE ... ADD VALUE is allowed inside a transaction on PostgreSQL 12+
-- as long as the new value is not *used* in the same transaction. It is not.
DO $$ BEGIN
    ALTER TYPE auth_method ADD VALUE IF NOT EXISTS 'client_credentials';
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE discovered_apps
    ADD COLUMN IF NOT EXISTS tenant_wide_consent BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_application_permissions BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE app_grants
    ADD COLUMN IF NOT EXISTS grant_type TEXT NOT NULL DEFAULT 'delegated';

-- The two Entra shapes that affect everyone at once; the dashboard leads with
-- them, so they get their own partial index rather than a sequential scan.
CREATE INDEX IF NOT EXISTS discovered_apps_unattended_idx
    ON discovered_apps (tenant_id, risk_score DESC)
    WHERE tenant_wide_consent OR has_application_permissions;

INSERT INTO schema_version (version) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO schema_version (version) VALUES (2) ON CONFLICT DO NOTHING;
