# Veyra Security Brain

A unified cybersecurity posture management (CSPM/SSPM) prototype. Veyra
connects to the SaaS and cloud platforms a company runs on, pulls their
security findings into one place, turns them into a single 0–100 risk
score, and tells you what to fix first, in plain language.

- **Backend:** Node.js + Express (`server/`). Express is the only required runtime
  dependency; the Claude and OpenAI SDKs are optional.
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

## AI, Auto-Fix and executive reporting

### Security Brain AI

Expand any recommendation (**AI analysis & fix code**) to get:

- **Executive summary & business impact** in plain language.
- **Fix code** tailored to the exact resource: AWS CLI, Terraform, Azure CLI,
  Microsoft Graph / Exchange PowerShell, GitHub CLI, Google Admin SDK or Slack
  API calls, with a copy button.
- **Side effects** to double-check before applying, plus the rollback.

The engine is chosen at startup:

| Configuration                     | Engine                                                         |
| --------------------------------- | -------------------------------------------------------------- |
| `ANTHROPIC_API_KEY` set           | Claude (`claude-opus-5-5` by default) via `@anthropic-ai/sdk`  |
| only `OPENAI_API_KEY` set         | OpenAI (`gpt-4o` by default, `OPENAI_MODEL` to change) via `openai` |
| no key                            | Rule-based engine: hand-written playbooks for all 39 checks    |

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # then: npm run dev
```

How the Claude integration behaves:

- Responses are constrained to a JSON schema (`output_config.format`), then
  validated and bounded before use.
- The request opts into server-side refusal fallback (`fallbacks: "default"`).
- Finding data is wrapped in tags and the system prompt tells the model to
  treat it as untrusted data. Resource names come from customer systems and
  could carry prompt injection.
- Results are cached per finding.

The service never fails a request. A timeout, refusal, malformed output,
missing SDK or bad key returns the rule-based analysis instead, with a
`fallbackReason`:

- **Bad key:** the provider is disabled until restart.
- **Repeated transient errors:** a 60-second cool-down starts.

Generated code is advisory text for a human. **Auto-Fix never executes
model output.** It only runs the vetted playbook actions.

### Auto-Fix

29 of the 39 checks have an automated playbook. The **Auto-Fix** button runs
it as a job. The dashboard shows each step live in a progress toast, and the
score animates up when the job finishes:

1. **Validate permissions:** integration connected and monitored, finding
   still open, and a just-in-time grant for the playbook's scoped permission
   (e.g. `s3:PutBucketPublicAccessBlock`).
2. **Capture rollback snapshot:** records the current configuration and how
   to undo the change.
3. **Execute fix:** the playbook's API calls (simulated in this prototype).
4. **Verify & resolve:** marks the finding `resolved` (`resolution: auto-fixed`).
5. **Recalculate risk score:** before and after values are recorded on the job.

The finding is claimed for the job's duration, so a manual remediation or a
second Auto-Fix gets `409`. The claim is re-validated before every step:

- **Integration paused or disconnected, or a demo reset mid-flight:** the job
  fails and the finding is released back to `open`.
- **Checks that must stay human-driven** (rotating a leaked key at its issuer,
  enforcing tenant-wide MFA, retention policy) return `422` with the reason.
  The UI offers **Mark resolved** for those.

### Executive PDF report

**Download Executive Report (PDF)** in the top bar produces a three-page A4
report:

- **Executive Security Summary:** score gauge, grade A–F, a narrative,
  severity KPIs and coverage.
- **Risk breakdown by platform:** Google Workspace, Microsoft 365, AWS, Azure,
  GitHub and Slack, each with its own score and severity counts.
- **Top 5 items requiring CISO action:** why each matters, the first action,
  effort, score gain, and whether Auto-Fix is available.
- **Compliance posture:** SOC 2 and ISO 27001 readiness with the largest
  control gaps.
- **Risk concentration by category.**

The PDF is produced by a small dependency-free writer (`server/src/lib/pdf.js`)
that uses the built-in Helvetica fonts. It adds no native or heavy dependencies.

**Compliance readiness:** every check maps to SOC 2 Trust Services Criteria and
ISO 27001:2022 Annex A controls, through its category and its explicit
references. Each check counts:

| Check state                          | Score |
| ------------------------------------ | ----- |
| Passing                              | 1     |
| Only medium/low findings open        | 0.5   |
| A critical or high finding open      | 0     |

A control's score is the mean of its checks, and readiness is the mean across
assessed controls. Each connector also runs a few baseline checks that pass in
the demo tenant (`server/src/connectors/baselineChecks.js`), as a real scan would.

## What you can do in the dashboard

- **Overview:** the overall security score (gauge, grade and 30-day trend),
  the count of critical vulnerabilities, open findings, active integrations,
  risk by category, and live status cards for each integration.
- **Security Brain Recommendations:** a prioritized feed. Each item shows
  its risk level (Critical / High / Medium / Low), the affected integration,
  a human-readable explanation, the business impact, a step-by-step playbook,
  compliance mappings, and the score gain you get by fixing it. **Auto-Fix**
  runs the playbook with live step-by-step progress; manual-only items offer
  **Mark resolved**. The analysis panel adds the AI summary, fix code and side
  effects.
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
│       │   ├── prioritize.js     # recommendation ranking + projected gain
│       │   └── compliance.js     # SOC 2 / ISO 27001 control mapping and readiness
│       ├── remediation/
│       │   └── playbooks.js      # per-check fix scripts, side effects, Auto-Fix actions
│       ├── services/
│       │   ├── aiService.js      # Claude / OpenAI / rule-based insights
│       │   ├── autoFix.js        # Auto-Fix job engine
│       │   └── reportPdf.js      # executive PDF layout
│       ├── lib/pdf.js            # dependency-free PDF writer
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
| GET    | `/findings/:id/insight?refresh=1`  | AI insight: summary, impact, fix code, side effects    |
| GET    | `/ai/status`                       | Active AI engine and why                                |
| POST   | `/remediate/auto-fix`              | Body `{ "findingId": "..." }`. Starts a job (202)      |
| GET    | `/remediate/jobs/:jobId`           | Job status with per-step progress                      |
| GET    | `/compliance`                      | SOC 2 / ISO 27001 readiness with per-control status    |
| GET    | `/reports/executive`               | Executive report data (JSON)                           |
| GET    | `/reports/pdf`                     | Executive report as a PDF download                     |
| POST   | `/demo/reset`                      | Restore the seeded demo state                          |

Errors use a consistent shape: `{ "error": "message" }`, plus a `fields` map
for validation errors. Status codes are 400 (invalid input), 404 (unknown
resource), 409 (invalid state, e.g. remediating twice), 422 (no automated fix
for this check) and 502 (scan failure).

### Configuration

| Variable                      | Default     | Purpose                                  |
| ----------------------------- | ----------- | ---------------------------------------- |
| `PORT`                        | `4000`      | API port                                 |
| `HOST`                        | `127.0.0.1` | Bind address (loopback by default)       |
| `VEYRA_CONNECTOR_LATENCY_MS`  | `900`       | Simulated provider API latency           |
| `VEYRA_REMEDIATION_DELAY_MS`  | `2500`      | Simulated duration of "Mark resolved"    |
| `VEYRA_AUTOFIX_STEP_MS`       | `700`       | Simulated duration of each Auto-Fix step |
| `ANTHROPIC_API_KEY`           |             | Enables Claude insights                  |
| `VEYRA_ANTHROPIC_MODEL`       | `claude-opus-5-5` | Claude model                       |
| `VEYRA_AI_EFFORT`             | `medium`    | Claude effort (`low` … `max`)            |
| `OPENAI_API_KEY` / `OPENAI_MODEL` |  / `gpt-4o` | Enables OpenAI insights (when no Anthropic key) |
| `VEYRA_AI_PROVIDER`           | `auto`      | `auto`, `anthropic`, `openai` or `rules` |
| `VEYRA_AI_TIMEOUT_MS`         | `45000`     | Per-request AI timeout                   |
| `VEYRA_TENANT_NAME`           | `Acme Corp` | Name on the report                       |
| `VEYRA_API_URL` (web)         | `http://127.0.0.1:4000` | Where the Vite dev server proxies `/api` |

## Prototype limits

- State is in memory. A restart (or **Reset demo data**) returns to the seeded tenant.
- There is no authentication on the API, which is why it binds to loopback by default.
  Put it behind SSO before exposing it anywhere.
- Connectors, remediation and Auto-Fix actions are simulated. No calls are made
  to any cloud or SaaS provider (the AI providers are the only external calls,
  and only when a key is set).
