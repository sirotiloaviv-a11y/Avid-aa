# Shadow IT Discovery

Find every third-party app your employees connected to Google Workspace or
Microsoft 365, score it, and tell you when something new and dangerous shows up.

An admin connects their tenant in about a minute. The service walks the
directory, asks the provider which OAuth clients hold which permissions,
collapses that into one row per app, scores it, and stores the diff so the next
scan can say *what changed*.

Built to be run by one person: one container, one Postgres, no queue, no worker
fleet. A customer can connect both providers at once — Workspace for the
company and Entra for an acquired subsidiary is a normal shape — and the
inventory, scoring and change feed are shared.

---

## Folder structure

```
shadow_it/
├── app/
│   ├── main.py                  FastAPI app factory, lifespan, CLI entry point
│   ├── config.py                every environment variable, in one dataclass
│   ├── crypto.py                Fernet envelope encryption + key rotation
│   ├── oauth_state.py           HMAC-signed, expiring OAuth state (both flows)
│   ├── db.py                    asyncpg pool, schema application, healthcheck
│   ├── models.py                provider-neutral domain types
│   ├── sql/
│   │   └── schema.sql           the whole database, idempotent
│   ├── connectors/
│   │   ├── base.py              the contract, and provider-neutral aggregation
│   │   ├── factory.py           provider -> connector, imported lazily
│   │   ├── google_workspace.py  Admin SDK: users.list + tokens.list
│   │   ├── graph_model.py       Graph payloads -> our model (pure, no HTTP)
│   │   └── microsoft365.py      Graph transport, paging, throttling, revocation
│   ├── risk/
│   │   ├── scopes.py            OAuth scope -> blast radius
│   │   ├── catalog.py           vendor -> category, and who is trusted
│   │   └── engine.py            scoring, bands, per-tenant policy
│   ├── services/
│   │   ├── repository.py        all SQL
│   │   ├── scanner.py           scan orchestration + the periodic scheduler
│   │   ├── google_oauth.py      Google admin-consent flow and revocation
│   │   └── microsoft_oauth.py   Entra admin-consent flow
│   └── api/
│       ├── deps.py              app context + API-key authentication
│       ├── tenants.py           tenant CRUD, API keys, policy rules
│       ├── connect.py           connect + callback + test, per provider
│       └── inventory.py         scans, app inventory, triage, revocation
├── tests/                       risk engine + Graph parsing (no DB, no network)
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
can test, tune, and argue about without a database. `connectors/graph_model.py`
follows the same rule for the Graph translation layer, and `factory.py` imports
each provider SDK lazily — so a Microsoft-only deployment never loads (or has
to keep patched) the Google libraries, and vice versa.

---

## How discovery works

The two providers answer the same question in structurally different ways, and
that difference is the whole reason they need separate connectors.

### Google Workspace — one call per employee

Google exposes exactly one endpoint that answers "what has this employee
connected?": `directory.tokens.list`, per user. There is no tenant-wide
version, so a scan is one API call per user plus directory pagination.

```
users.list          ->  every account (paginated, 500/page)
tokens.list(user)   ->  clientId, displayText, scopes[], anonymous, nativeApp
     fan out across a thread pool, back off on 429
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

### Microsoft 365 — directory-wide collections

Entra exposes grants as tenant-wide collections, so the same scan is a handful
of paginated reads no matter how big the company is. A 5,000-seat Entra scan
costs less than a 200-seat Workspace one.

```
users                                     the directory
directoryRoles?$expand=members            who is privileged
servicePrincipals                         every app identity, plus each API's
                                          appRole id -> name map
oauth2PermissionGrants                    delegated consent, tenant-wide
servicePrincipals/{id}/appRoleAssignments app-only permissions, per third-party app
```

Entra also has two grant shapes Google simply does not have, and both are worse
than anything `tokens.list` can return:

| Shape | What it means |
|---|---|
| **Tenant-wide consent** (`consentType: AllPrincipals`) | An admin consented on behalf of every employee. Nobody opted in; nobody can opt out. |
| **Application permissions** (app role assignments) | App-only access with no user in the loop at all. It keeps reading the tenant after the employee who introduced it has left. |

Both get their own principal in the model — `(all users — admin consent)` and
`(application — no user)` — and are deliberately kept out of the user count, so
"8 users" always means eight people.

Microsoft's analogue of Google's `anonymous` flag is a service principal with
no `verifiedPublisher`. That is also true of an app registered inside the
customer's own directory, which is correct: an employee's personal registration
holding `Mail.Read.All` is precisely what this product exists to surface.

**Required application permissions** on the multi-tenant app registration:

```
Application.Read.All   read service principals and their app role assignments
Directory.Read.All     read users, directory roles and delegated grants
```

Revocation additionally needs `DelegatedPermissionGrant.ReadWrite.All` and
`AppRoleAssignment.ReadWrite.All`. Both are optional on purpose — discovery
works without them, and a read-only consent screen is far easier to sell.

Microsoft first-party service principals (Outlook, Teams, and several hundred
others) and Azure managed identities are filtered out: they are not third-party
apps, and leaving them in would bury the report.

### Then, identically for both

```
aggregate by client id  ->  one DiscoveredApp: union of scopes, set of users,
                            admin count, Entra grant shapes
score against tenant policy
persist + diff against the previous scan  ->  app_events
```

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
- **Publisher signals.** Unverifiable publisher +15 (Google: unregistered
  client; Microsoft: no verified publisher), native app +5.
- **Reach.** Authorized by an admin +15; widely installed (10+ users, or 25% of
  the directory) +8; 3+ users +4.
- **Entra grant shape.** Tenant-wide admin consent +15 (it replaces the
  install-count bonus rather than stacking with it); app-only permissions +18.
- **Write access.** +8 when the app can change or delete data, not just read it.
- **Trusted vendor.** −12 for a short list of names a tech company almost
  certainly procured on purpose.

**Floors and caps** — these exist because the modifiers alone get it wrong at
the edges:

- Any weight-10 scope floors the app at high. Being a known brand is not a
  mitigation for "can read every file in the company".
- Unverified publisher + write access floors at high.
- App-only permissions on a sensitive API floor at high. It is a standing,
  unattended foothold in the tenant, and vendor reputation does not change that.
- Identity-only apps are capped at low. If "Sign in with Google" apps land in
  medium, nobody reads the report after week one. The cap does *not* apply to a
  tenant-wide or app-only grant — consenting for the whole directory is worth a
  look even when the scopes are harmless.
- Tenant allowlist forces low; blocklist forces high.

Graph permissions get one extra rule of their own: a `.All` suffix widens a
permission from the signed-in user to the whole tenant (`Mail.Read` is one
mailbox, `Mail.Read.All` is every mailbox), so it adds a point wherever the
table falls back to a prefix match.

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
| `tenant_credentials` | the provider credential, **Fernet-encrypted**, one active row per tenant+provider (Google: a refresh token; Microsoft: the customer's Entra tenant id) |
| `directory_users` | the customer's directory, refreshed each scan |
| `discovered_apps` | one row per client id: scopes, users, score, band, reasons, triage status |
| `app_grants` | the atomic fact — principal X authorized app Y with scopes Z, tagged `delegated` / `tenant_wide` / `application` |
| `scans` | scan history, counts, partial-failure errors |
| `app_events` | the change feed: app discovered, scopes widened, risk rose |
| `policy_rules` | per-tenant allowlist/blocklist |

Two invariants hold everywhere: every customer row carries `tenant_id` and
every query filters on it, and secrets are `BYTEA` ciphertext, never text.

`schema.sql` carries its own additive migrations (`ADD COLUMN IF NOT EXISTS`,
`ALTER TYPE ... ADD VALUE IF NOT EXISTS`), so a v1 database picks up the
Microsoft columns on the next boot with nothing to run by hand.

---

## Setup

Configure at least one provider. Google-only and Microsoft-only deployments
are both supported shapes; `GET /v1/connect/providers` reports what is enabled.

**1a. Google Cloud project**

- Create an OAuth client ID (type: Web application).
- Authorized redirect URI: `${PUBLIC_BASE_URL}/v1/connect/google/callback`
  — it must match exactly, including scheme and trailing slash.
- Enable the **Admin SDK API** on the same project.
- Configure the OAuth consent screen. Publishing it (or having customers
  allowlist the client id in *Workspace Admin → Security → API controls*) is
  what lets other domains consent.

**1b. Entra ID app registration**

- Azure portal → App registrations → New registration, **multi-tenant**
  ("Accounts in any organizational directory"). One registration serves every
  customer; they admin-consent to it.
- Redirect URI (type Web): `${PUBLIC_BASE_URL}/v1/connect/microsoft/callback`
- API permissions, type **Application** (not Delegated): `Application.Read.All`,
  `Directory.Read.All`. Add `DelegatedPermissionGrant.ReadWrite.All` and
  `AppRoleAssignment.ReadWrite.All` only if you want in-app revocation.
- Certificates & secrets → New client secret. **Note the expiry**: when it
  lapses, every customer's scan fails at once. Put a reminder in a calendar.

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

# get a consent URL and send the customer's admin to it
curl -s "localhost:8000/v1/connect/google/start/$TENANT_ID" \
  -H "Authorization: Bearer $API_KEY"
curl -s "localhost:8000/v1/connect/microsoft/start/$TENANT_ID" \
  -H "Authorization: Bearer $API_KEY"   # needs a Global Administrator

# scan every connected provider (returns immediately; poll for progress)
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
| `GET` | `/v1/connect/providers` | which providers this deployment can onboard |
| `GET` | `/v1/connect/google/start/{id}` | Google consent URL |
| `GET` | `/v1/connect/google/callback` | Google's redirect target |
| `POST` | `/v1/connect/google/{id}/test` | is the connection still alive? |
| `GET` | `/v1/connect/microsoft/start/{id}` | Entra admin-consent URL |
| `GET` | `/v1/connect/microsoft/callback` | Entra's redirect target |
| `POST` | `/v1/connect/microsoft/{id}/test` | is the connection still alive? |
| `POST` | `/v1/tenants/{id}/scans` | start a scan — all connected providers, or `?provider=` |
| `GET` | `/v1/tenants/{id}/scans/latest` | scan status and counts, overall and per provider |
| `GET` | `/v1/tenants/{id}/summary` | counts by band, connected providers, last scan each |
| `GET` | `/v1/tenants/{id}/apps` | inventory; filter by band, status, category, provider, search |
| `GET` | `/v1/tenants/{id}/apps/{app_id}` | one app, with every grant |
| `PATCH` | `/v1/tenants/{id}/apps/{app_id}` | triage: approved / blocked / ignored |
| `POST` | `/v1/tenants/{id}/apps/{app_id}/revoke` | revoke access (needs `confirm: true`) |
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
That shapes the design. (The Microsoft side is deliberately lighter: the only
customer-specific value stored is an Entra tenant id, a public GUID. A database
breach there leaks nothing usable on its own — an attacker would also need our
client secret, which lives only in the process environment.)

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
  form field, and a personal account (no `hd` claim) is rejected. On the Entra
  side the returned tenant id is validated as a GUID before it is ever
  interpolated into a token URL.
- **Credentials are proved before they are stored**, and revoked upstream if
  the probe fails, so a half-working connection never reaches a scheduled scan.
- **Revocation is opt-in, confirmed, and per-principal.** A scan never revokes
  anything; a tool that silently cuts employees off from their apps gets
  uninstalled the same week. The provider comes from the stored app row, not
  from the request, so a caller cannot redirect where we send a delete.
- **Least privilege on both sides**: two read-only Admin SDK scopes for
  Google, two read-only application permissions for Graph. The write
  permissions needed for revocation are optional and separately consented.

If a Google customer disconnects, call `google_oauth.revoke_refresh_token` —
holding a live super-admin token for a company that left is liability with no
upside. A Microsoft customer revokes at their end by removing the enterprise
application; after that our client-credentials requests simply stop working.

---

## Testing

```bash
python -m unittest discover -s tests -t .
```

47 tests covering scope weighting, categorization, banding, policy overrides,
aggregation, and the Graph translation layer (service principal parsing,
delegated vs tenant-wide vs app-only grants, appRole id resolution). No
database, no network, no credentials — the Graph tests run against captured
response shapes.

---

## Deployment notes

- **One API container.** The scheduler loop lives in-process; running two
  replicas runs two schedulers. To scale out, set `SCAN_INTERVAL_HOURS=0` on
  the extra replicas and keep one scheduler instance. The in-process scan lock
  has the same constraint — the swap is a Postgres advisory lock, noted in
  `services/scanner.py`.
- **Google scan cost is linear in seats.** `tokens.list` is one call per user;
  `SCAN_CONCURRENCY=8` is comfortably inside the default Admin SDK quota. Raise
  it only after requesting more quota, or you will spend the scan in backoff.
  Microsoft is not seat-linear — it reads directory-wide collections, and
  concurrency there only bounds the per-app `appRoleAssignments` calls.
- **Watch the Entra client secret expiry.** It is a single shared secret; when
  it lapses every customer scan fails at once with an auth error.
- **`SCAN_MAX_USERS`** caps a scan — useful for trials and smoke tests. On
  Microsoft it only truncates the user list used to name principals, so
  some grants come back attributed to `(unknown principal ...)`.
- **Back up `ENCRYPTION_KEY` outside the database.** Losing it means every
  customer reconnects.

## Roadmap

The parts deliberately left out, in the order they pay off:

1. **Notifications.** `app_events` rows already carry `notified_at` — a digest
   job reading unsent events into Slack or email is the alerting product. The
   two Entra escalation events (`tenant_wide_consent_granted`,
   `application_permissions_granted`) are the ones worth paging on.
2. **A dashboard.** The API is complete enough to build one against.
3. **Preventive controls**: Workspace API access controls and Entra's "user
   consent for applications" setting, so blocking an app in this tool actually
   blocks it at the provider.
4. **Sign-in telemetry.** Entra exposes last sign-in per service principal; an
   app nobody has used in a year is the easiest revocation to approve.
