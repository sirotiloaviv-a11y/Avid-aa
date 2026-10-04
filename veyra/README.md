# Veyra Security Brain

A unified cybersecurity posture management (CSPM/SSPM) prototype. Veyra
connects to the SaaS and cloud platforms a company runs on, pulls their
security findings into one place, turns them into a single 0–100 risk
score, and tells you what to fix first, in plain language.

- **Backend:** Node.js + Express (`server/`). The only runtime dependency is Express.
- **Frontend:** React 18 + Vite + Tailwind CSS (`web/`), with a dark executive dashboard.
- **Integrations:** Google Workspace, Microsoft 365, AWS, Azure, GitHub, Slack.
  Each one has its own connector and mock data generator, and all run in simulation mode.

## Quick start

Requires Node.js 20 or newer.

```bash
cd veyra
npm run setup      # installs server/ and web/ dependencies
npm run dev        # API on :4000 + dashboard on :5173
```

Open http://127.0.0.1:5173.

The demo tenant ("Acme Corp") starts with Google Workspace, AWS, GitHub
and Slack connected. Microsoft 365 and Azure are left disconnected so you
can try the connect flow; use **Use demo values** in the connect dialog.

Other commands:

| Command         | What it does                                                         |
| --------------- | -------------------------------------------------------------------- |
| `npm start`     | Builds the dashboard and serves app + API from one port (`:4000`)    |
| `npm test`      | API test suite (`node:test`, no extra dependencies)                  |
| `npm run build` | Production build of the dashboard into `web/dist`                    |

## What you can do in the dashboard

- **Overview:** the overall security score (gauge, grade and 30-day trend),
  the count of critical vulnerabilities, open findings, active integrations,
  risk by category, and live status cards for each integration.
- **Security Brain Recommendations:** a prioritized feed. Each item shows
  its risk level (Critical / High / Medium / Low), the affected integration,
  a human-readable explanation, the business impact, a step-by-step playbook,
  compliance mappings, and the score gain you get by fixing it. **Remediate**
  runs the playbook, and the score updates as soon as it completes.
- **Findings:** a searchable, filterable table of every finding, with evidence.
- **Integrations:** connect and disconnect each provider, pause or resume
  monitoring with a toggle, and trigger a rescan. The connect dialog lists
  the exact read-only scopes requested.

## Architecture

```
veyra/
├── server/
│   └── src/
│       ├── index.js              # boot: seed demo tenant, start HTTP server
│       ├── app.js                # Express routes, validation, error handling
│       ├── brain.js              # SecurityBrain: integration state, findings, scoring
│       ├── config.js             # env config + demo connections
│       ├── engine/
│       │   ├── risk.js           # score model, grades, breakdowns
│       │   └── prioritize.js     # recommendation ranking + projected gain
│       ├── connectors/
│       │   ├── BaseConnector.js  # connector contract (validate → authenticate → collect)
│       │   ├── index.js          # registry
│       │   └── providers/        # googleWorkspace, microsoft365, aws, azure, github, slack
│       └── mock/
│           ├── generateFindings.js  # deterministic finding generator
│           └── pools.js             # names, repos, buckets, docs, ...
├── web/
│   └── src/
│       ├── App.jsx               # layout, sidebar, hash routing
│       ├── lib/                  # API client, state/polling context, formatting
│       ├── components/           # gauge, sparkline, recommendation cards, modal, toasts
│       └── views/                # Overview, Recommendations, Findings, Integrations
└── scripts/
    ├── dev.mjs                   # runs API + Vite together
    └── smoke.cjs                 # Playwright smoke test used in CI
```

### Connectors

Every provider is a definition object run by `BaseConnector`:

- `credentialFields`: the identifiers the user enters (tenant ID, role ARN,
  org name, and so on), with validation patterns shared by server and browser.
  Veyra never asks for passwords or secret keys. Access is granted through each
  vendor's own consent mechanism (GitHub App, AWS cross-account role,
  Entra admin consent, Google domain-wide delegation, Slack OAuth).
- `scopes` / `authMethod`: what a production connector would request.
- `templates`: the security checks. Each template generates findings with
  title, severity, category, exposure, explanation, impact, remediation steps,
  effort, compliance mappings and evidence.

To make a connector real, override `authenticate()` (token exchange /
AssumeRole) and `collect()` (API calls) in a subclass. Nothing else changes,
because the engine only sees findings.

Mock data is **deterministic**: resources are seeded by provider, account and
check, so findings keep stable IDs across restarts and rescans. Checks marked
with a `probability` below 1 simulate configuration drift, so they may appear
or disappear between scans.

Signature simulated findings include GitHub exposed secrets, public AWS S3
buckets and a root account without MFA, unverified external Super Admins in
Google Workspace, excessive public file sharing in Slack, MFA gaps and
malicious inbox rules in Microsoft 365, and anonymous blob access in Azure.

### Risk score

```
penalty(finding) = severity weight × exposure multiplier
                   critical 10, high 5, medium 2, low 0.5
                   public ×1.5, external ×1.25, internal ×1
score = round(100 × e^(−Σ penalty / 200))
```

The score is bounded to 0–100. The first critical issues move it the most,
and fixing anything always raises it. Per-integration and per-category scores
use a tighter scale (60). Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 55, F below.

Coverage (monitored sources out of 6) is reported **next to** the score, not
folded into it. Connecting a new source that surfaces real problems lowers
the score honestly rather than inflating it. Pausing an integration removes
its findings from the score until monitoring resumes.

Recommendations are ordered by severity first. Within a severity they are
ordered by `penalty × exploitability × ageing`, where ageing adds up to +50%
for issues open around a month or longer. Each one carries `projectedGain`, the exact
number of points the overall score rises if that finding is fixed.

## API

All endpoints are JSON under `/api`.

| Method | Path                               | Description                                            |
| ------ | ---------------------------------- | ------------------------------------------------------ |
| GET    | `/health`                          | Liveness                                               |
| GET    | `/dashboard`                       | Score, integrations, recommendations, activity: one call |
| GET    | `/risk-score`                      | Score, grade, severity counts, coverage, breakdowns, trend |
| GET    | `/recommendations?limit=`          | Prioritized recommendations                            |
| GET    | `/findings?provider=&severity=&status=&q=` | Filtered findings                              |
| GET    | `/findings/:id`                    | One finding with evidence                              |
| POST   | `/findings/:id/remediate`          | Start remediation (202). Resolves after a short delay  |
| GET    | `/integrations`                    | All integrations with status and finding counts        |
| GET    | `/integrations/:id`                | One integration                                        |
| POST   | `/integrations/:id/connect`        | Body `{ "credentials": { ... } }`. Validates, connects, scans |
| POST   | `/integrations/:id/disconnect`     | Disconnect and drop its findings                       |
| PATCH  | `/integrations/:id`                | Body `{ "enabled": boolean }`. Pause or resume monitoring |
| POST   | `/integrations/:id/sync`           | Rescan one integration                                 |
| POST   | `/sync`                            | Rescan all monitored integrations                      |
| POST   | `/demo/reset`                      | Restore the seeded demo state                          |

Errors use a consistent shape: `{ "error": "message" }`, plus a `fields` map
for validation errors. Status codes are 400 (invalid input), 404 (unknown
resource), 409 (invalid state, e.g. remediating twice) and 502 (scan failure).

### Configuration

| Variable                      | Default     | Purpose                                  |
| ----------------------------- | ----------- | ---------------------------------------- |
| `PORT`                        | `4000`      | API port                                 |
| `HOST`                        | `127.0.0.1` | Bind address (loopback by default)       |
| `VEYRA_CONNECTOR_LATENCY_MS`  | `900`       | Simulated provider API latency           |
| `VEYRA_REMEDIATION_DELAY_MS`  | `2500`      | Simulated remediation playbook duration  |
| `VEYRA_API_URL` (web)         | `http://127.0.0.1:4000` | Where the Vite dev server proxies `/api` |

## Prototype limits

- State is in memory. A restart (or **Reset demo data**) returns to the seeded tenant.
- There is no authentication on the API, which is why it binds to loopback by default.
  Put it behind SSO before exposing it anywhere.
- Connectors and remediation are simulated. No calls are made to any provider.
