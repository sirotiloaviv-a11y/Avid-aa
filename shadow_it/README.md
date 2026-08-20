# Shadow IT Discovery

Find every third-party app your employees connected to Google Workspace, score
it, and tell you when something new and dangerous shows up.

An admin connects their Workspace in about a minute. The service walks the
directory, asks Google which OAuth clients each user has authorized and with
which scopes, collapses that into one row per app, scores it, and stores the
diff so the next scan can say *what changed*.

Built to be run by one person: one container, one Postgres, no queue, no
worker fleet, no vendor SDK beyond Google's own.

---

## Folder structure

```
shadow_it/
├── app/
│   ├── main.py                  FastAPI app factory, lifespan, CLI entry point
│   ├── config.py                every environment variable, in one dataclass
│   ├── crypto.py                Fernet envelope encryption + key rotation
│   ├── db.py                    asyncpg pool, schema application, healthcheck
│   ├── models.py                provider-neutral domain types
│   ├── sql/
│   │   └── schema.sql           the whole database, idempotent
│   ├── connectors/
│   │   ├── base.py              the contract a provider connector implements
│   │   └── google_workspace.py  Admin SDK: users.list + tokens.list
│   ├── risk/
│   │   ├── scopes.py            OAuth scope -> blast radius
│   │   ├── catalog.py           vendor -> category, and who is trusted
│   │   └── engine.py            scoring, bands, per-tenant policy
│   ├── services/
│   │   ├── repository.py        all SQL
│   │   ├── scanner.py           scan orchestration + the periodic scheduler
│   │   └── google_oauth.py      admin-consent flow, signed state, revocation
│   └── api/
│       ├── deps.py              app context + API-key authentication
│       ├── tenants.py           tenant CRUD, API keys, policy rules
│       ├── connect.py           OAuth connect + callback + connection test
│       └── inventory.py         scans, app inventory, triage, revocation
├── tests/                       risk-engine tests (no database, no network)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

The dependency direction is one-way and worth preserving:

```
api  ->  services  ->  connectors + risk  ->  models
                 \->  repository -> db
```

`risk/` imports nothing but `models`. That is what keeps it a pure function you
can test, tune, and argue about without a database.

---

## How discovery works

Google exposes exactly one endpoint that answers "what has this employee
connected?": `directory.tokens.list`, per user. There is no tenant-wide
version, so a scan is one API call per user plus directory pagination.

```
users.list          ->  every account (paginated, 500/page)
tokens.list(user)   ->  clientId, displayText, scopes[], anonymous, nativeApp
     fan out across a thread pool, back off on 429
aggregate by clientId
     -> one DiscoveredApp: union of scopes, set of users, admin count
score against tenant policy
persist + diff against the previous scan  ->  app_events
```

Three fields do most of the work:

| Field | Why it matters |
|---|---|
| `scopes` | The only honest description of what an app can do. Names lie. |
| `anonymous` | `true` means the client is registered to no verified project — Google itself cannot name the publisher. The strongest single Shadow IT signal. |
| `nativeApp` | Installed desktop/mobile client; its OAuth secret cannot be protected. |

**Required scopes** (least privilege — admins do read the consent screen):

```
https://www.googleapis.com/auth/admin.directory.user.readonly   list users
https://www.googleapis.com/auth/admin.directory.user.security   read/revoke tokens
```

Plus `openid email`, used only to identify the admin who consented.

---

## Risk scoring

Scores are 0–100 and land in three bands: **high ≥ 70**, **medium ≥ 40**,
**low** below that. Every score carries the reasons that produced it, and the
API returns them verbatim so a customer can audit a finding without asking you.

Scoring is a pure function of the app plus the tenant's policy — no clock, no
model call, same input, same score.

**Inputs**

- **Scope weight (0–60).** Highest-sensitivity scope × 6. Full mailbox, full
  Drive, directory write and `cloud-platform` are weight 10; `drive.file` is 2;
  `openid`/`email`/`profile` are 0.
- **Scope breadth (0–10).** Extra points per additional high-sensitivity scope.
- **Category.** AI meeting recorders +20, AI/LLM tools +18, remote access +18,
  file sharing +15, developer tools +12, browser extensions +12, outreach tools
  +12, unclassified +8, security/IT tooling +0.
- **Publisher signals.** Unregistered ("anonymous") client +15, native app +5.
- **Reach.** Authorized by an admin +15; widely installed (10+ users, or 25% of
  the directory) +8; 3+ users +4.
- **Write access.** +8 when the app can change or delete data, not just read it.
- **Trusted vendor.** −12 for a short list of names a tech company almost
  certainly procured on purpose.

**Floors and caps** — these exist because the modifiers alone get it wrong at
the edges:

- Any weight-10 scope floors the app at high. Being a known brand is not a
  mitigation for "can read every file in the company".
- Unverified publisher + write access floors at high.
- Identity-only apps are capped at low. If "Sign in with Google" apps land in
  medium, nobody reads the report after week one.
- Tenant allowlist forces low; blocklist forces high.

Tune the constants at the top of `app/risk/engine.py`; the tests in
`tests/test_risk_engine.py` assert the behaviour that should survive tuning
(ordering, bands, bounds, explainability) rather than exact numbers.

---

## Database

PostgreSQL 13+ (for `gen_random_uuid()`). `app/sql/schema.sql` is idempotent
and applied on boot, so a fresh deploy needs no migration tool.

| Table | Holds |
|---|---|
| `tenants` | one row per customer company, plus directory size for scoring |
| `api_keys` | dashboard/API keys, **hashed** — a dump yields no working keys |
| `tenant_credentials` | the admin refresh token, **Fernet-encrypted**, one active row per tenant+provider |
| `directory_users` | the customer's directory, refreshed each scan |
| `discovered_apps` | one row per client id: scopes, users, score, band, reasons, triage status |
| `app_grants` | the atomic fact — user X authorized app Y with scopes Z |
| `scans` | scan history, counts, partial-failure errors |
| `app_events` | the change feed: app discovered, scopes widened, risk rose |
| `policy_rules` | per-tenant allowlist/blocklist |

Two invariants hold everywhere: every customer row carries `tenant_id` and
every query filters on it, and secrets are `BYTEA` ciphertext, never text.

---

## Setup

**1. Google Cloud project**

- Create an OAuth client ID (type: Web application).
- Authorized redirect URI: `${PUBLIC_BASE_URL}/v1/connect/google/callback`
  — it must match exactly, including scheme and trailing slash.
- Enable the **Admin SDK API** on the same project.
- Configure the OAuth consent screen. Publishing it (or having customers
  allowlist the client id in *Workspace Admin → Security → API controls*) is
  what lets other domains consent.

**2. Configure and run**

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
python -c "import secrets;print('sk_'+secrets.token_urlsafe(32))"                          # API_KEY
docker compose up --build
```

Or without Docker:

```bash
pip install -r requirements.txt
python -m app.main --check      # validate configuration
python -m app.main --migrate    # apply the schema
uvicorn app.main:app --reload
```

**3. Onboard a customer**

```bash
# create the tenant (returns its API key once — store it)
curl -sX POST localhost:8000/v1/tenants \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Acme","primary_domain":"acme.com"}'

# get the consent URL and send the Workspace super-admin to it
curl -s "localhost:8000/v1/connect/google/start/$TENANT_ID" \
  -H "Authorization: Bearer $API_KEY"

# scan (returns immediately; poll for progress)
curl -sX POST "localhost:8000/v1/tenants/$TENANT_ID/scans" -H "Authorization: Bearer $API_KEY"
curl -s "localhost:8000/v1/tenants/$TENANT_ID/scans/latest" -H "Authorization: Bearer $API_KEY"

# read the inventory
curl -s "localhost:8000/v1/tenants/$TENANT_ID/apps?band=high" -H "Authorization: Bearer $API_KEY"
```

You can also run a scan straight from the CLI: `python -m app.main --scan <tenant_id>`.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/tenants` | create a customer, mint its API key |
| `GET` | `/v1/tenants` | list customers (operator key) |
| `GET` | `/v1/tenants/{id}` | tenant detail |
| `POST` | `/v1/tenants/{id}/policy` | add an allowlist/blocklist rule |
| `GET` | `/v1/connect/google/start/{id}` | get the admin consent URL |
| `GET` | `/v1/connect/google/callback` | Google's redirect target |
| `POST` | `/v1/connect/google/{id}/test` | is the connection still alive? |
| `POST` | `/v1/tenants/{id}/scans` | start a scan (202, runs in background) |
| `GET` | `/v1/tenants/{id}/scans/latest` | scan status and counts |
| `GET` | `/v1/tenants/{id}/summary` | counts by band, last scan |
| `GET` | `/v1/tenants/{id}/apps` | inventory; filter by band, status, category, search |
| `GET` | `/v1/tenants/{id}/apps/{app_id}` | one app, with every grant |
| `PATCH` | `/v1/tenants/{id}/apps/{app_id}` | triage: approved / blocked / ignored |
| `POST` | `/v1/tenants/{id}/apps/{app_id}/revoke` | revoke tokens (needs `confirm: true`) |
| `GET` | `/v1/tenants/{id}/events` | change feed |
| `GET` | `/healthz` | liveness + database |

Interactive docs at `/docs`.

Two kinds of key: the **operator key** (`API_KEY`) works everywhere, and a
**tenant key** works only for its own tenant. `require_tenant` in
`app/api/deps.py` is the entire isolation boundary on the read path — keep it
that way.

---

## Security notes

This product holds Workspace super-admin refresh tokens for other companies.
That shapes the design:

- **Tokens are encrypted at rest** with Fernet; the key lives in the process
  environment, never in the database. `ENCRYPTION_KEYS` holds retired keys so
  rotation does not orphan old rows.
- **`repository.load_credentials` is the only decryption site.** Credentials
  never appear in an API response, and `TenantCredentials.__repr__` is
  redacted so a traceback cannot leak one.
- **API keys are stored as SHA-256 hashes**, compared in constant time.
- **The OAuth `state` is HMAC-signed and expires in 10 minutes.** Without that,
  the callback is a CSRF hole that binds the wrong Workspace to a tenant.
- **The admin's identity comes from Google's signed `id_token`**, not from a
  form field, and a personal account (no `hd` claim) is rejected.
- **Credentials are proved before they are stored**, and revoked upstream if
  the probe fails, so a half-working connection never reaches a scheduled scan.
- **Revocation is opt-in, confirmed, and per-user.** A scan never revokes
  anything; a tool that silently cuts employees off from their apps gets
  uninstalled the same week.
- **Least privilege, and only readonly + token-security scopes.**

If a customer disconnects, call `google_oauth.revoke_refresh_token` — holding a
live super-admin token for a company that left is liability with no upside.

---

## Testing

```bash
python -m unittest discover -s tests -t .
```

26 tests covering scope weighting, categorization, banding, policy overrides
and aggregation. No database, no network, no credentials.

---

## Deployment notes

- **One API container.** The scheduler loop lives in-process; running two
  replicas runs two schedulers. To scale out, set `SCAN_INTERVAL_HOURS=0` on
  the extra replicas and keep one scheduler instance. The in-process scan lock
  has the same constraint — the swap is a Postgres advisory lock, noted in
  `services/scanner.py`.
- **Scan cost is linear in seats.** `tokens.list` is one call per user;
  `SCAN_CONCURRENCY=8` is comfortably inside the default Admin SDK quota. Raise
  it only after requesting more quota, or you will spend the scan in backoff.
- **`SCAN_MAX_USERS`** caps a scan — useful for trials and smoke tests.
- **Back up `ENCRYPTION_KEY` outside the database.** Losing it means every
  customer reconnects.

## Roadmap

The parts deliberately left out of the MVP, in the order they pay off:

1. **Microsoft 365 connector.** `connectors/base.py` is the contract and
   `risk/scopes.py` already carries a Graph permission table; the work is
   Graph's `servicePrincipals` / `oauth2PermissionGrants` and app-only auth.
2. **Notifications.** `app_events` rows already carry `notified_at` — a digest
   job reading unsent events into Slack or email is the alerting product.
3. **A dashboard.** The API is complete enough to build one against.
4. **OAuth app allowlisting via Workspace API controls**, so blocking an app in
   this tool actually blocks it in Google.
