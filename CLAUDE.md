# CLAUDE.md

Guidance for AI assistants working in this repository.

## What this repository is

Two **independent** security projects that share a git repo and nothing else —
no shared code, no shared dependencies, no shared test suite. Treat them as
separate codebases that happen to live side by side.

| Directory | Project | Language / deps |
| --- | --- | --- |
| `moat/` | Security scanner for AI agent and MCP configuration. Packaged and published as `moat-scanner`. | Python 3.10+, **zero runtime dependencies** |
| `security_alert_system/` | Hebrew-language security-alert monitor (RSS + Telegram → keyword match → Telegram alert), with an AI assistant, voice, a dashboard and an ingest route. | Python 3.10+, `httpx`, `feedparser`, optional `anthropic` |
| `examples/` | Two sample agent projects (`vulnerable-` and `hardened-`) used as moat's documentation **and** as test fixtures. | — |
| `bridges/` | Docs only. Contract for out-of-process sources that push into the alert system. | — |
| `tests/` | moat's test suite. | stdlib `unittest` |
| `security_alert_system/tests/` | The alert system's test suite. | stdlib `unittest` |

`pyproject.toml` at the root packages **moat only**. The alert system is not
packaged; it is run as a module from the repo root or via Docker.

The per-project READMEs (`moat/README.md`, `security_alert_system/README.md`)
are detailed and current. Read the relevant one before changing behaviour — they
document design decisions, not just usage, and several of those decisions are
asserted by tests.

## Commands

Two test suites, two commands. **Neither one runs the other's tests.**

```bash
# moat — 114 tests, no dependencies, runs anywhere
python -m unittest discover -s tests -t . -v

# alert system — 136 tests, needs the requirements installed first
pip install -r security_alert_system/requirements.txt
python -m unittest discover -s security_alert_system/tests -t .
```

Without `httpx` / `feedparser` / `anthropic` installed, four of the six alert-system
test modules fail at import (`test_assistant`, `test_ingest`, `test_pipeline`,
`test_voice`) and only the 53 tests in `test_keywords` and `test_dashboard` run. That is a missing-dependency error, not a
regression — install the requirements before concluding anything about a failure
there.

Always run tests from the **repository root**; both suites rely on `-t .` for
package imports to resolve.

```bash
# moat, run from source
python -m moat .                                   # scan this repo
python -m moat examples/vulnerable-agent-project   # 22 findings, 10 critical
python -m moat examples/hardened-agent-project     # 2 low, exit 0
python -m moat --list-rules

# alert system
python -m security_alert_system.main --check       # validate config, exit
python -m security_alert_system.main --chat-id     # discover your Telegram chat id
python -m security_alert_system.main --test        # send one test alert
python -m security_alert_system.main               # monitor + dashboard
python -m security_alert_system.main --dashboard   # dashboard only, no polling
docker compose up -d                               # 24/7 deployment
```

## CI

`.github/workflows/moat.yml` does two things, both scoped to moat:

- `test` — runs **only `tests/`** on Python 3.10–3.13. The alert system's suite
  is not in CI; if you change that project, run its tests locally.
- `scan` — moat scans this repository's own agent config, uploads SARIF to code
  scanning, then fails on high-severity findings. `examples/*` is excluded,
  because it contains a deliberately vulnerable project.

A weekly cron re-runs the scan: agent config drifts without a code change.

## moat

### Architecture

```
discovery.collect() → [Target]  →  per-file rules (REGISTRY)          ┐
                                →  whole-project rules (PROJECT_REGISTRY) ┘ → [Finding]
                                → filter (baseline / min-severity / dedupe) → sort → reporter
```

| File | Role |
| --- | --- |
| `models.py` | `Severity`, `Target`, `Finding`, `Rule`. The vocabulary everything else speaks. |
| `discovery.py` | Locates and classifies agent config across hosts (Claude, Cursor, VS Code, Cline). |
| `loader.py` | Tolerant JSON (comments, trailing commas) and markdown frontmatter parsing. |
| `capabilities.py` | Maps a tool grant to what it actually lets an agent do. The analytical core. |
| `rules/` | One module per family; checks registered by decorator. |
| `reporters/` | `text` (humans), `json` (pipelines), `sarif` (GitHub code scanning). |
| `scanner.py` | Orchestration, baseline suppression, filtering, sorting. |
| `cli.py` | argparse front end. Exit `0` clean, `1` findings at/above `--fail-on`, `2` usage error. |

### Rules that are not negotiable

**Zero runtime dependencies.** `dependencies = []` in `pyproject.toml` is a
product decision, stated in the file: a scanner that warns about supply-chain
risk must not arrive with a dependency tree of its own. Never add an import
outside the standard library to `moat/`. Test-only helpers are stdlib too
(`unittest`, not pytest).

**Unknown means dangerous.** An MCP server `capabilities.py` does not recognise
is scored as holding *every* capability. Failing open would let an unrecognised
server hide a trifecta. Do not "fix" this by defaulting to `NONE`.

**Every finding must state its consequence and its fix.** `tests/test_cli.py`
asserts `len(finding.impact) > 40` and `len(finding.remediation) > 20` on every
finding the rules can produce. `impact` is what an attacker gets — never a
restatement of the title. `remediation` is the concrete change.

**Credentials are redacted everywhere.** A report gets pasted into chat.
`tests/test_examples.py` asserts no detected secret appears in any output field.

**Every rule needs a negative test.** A scanner that cries wolf gets muted.
`tests/test_rules.py` pairs each positive case with a false-positive guard
(`assertFinds` / `assertClean` from `tests/helpers.py`).

**Fingerprints exclude line numbers** (`Finding.fingerprint`), so reformatting a
config does not resurrect a triaged finding. Do not add `line` to the seed.

### Adding a rule

Registration is by decorator; there is no central list to edit.

```python
from moat.models import AGENT_SETTINGS, Finding, Severity
from moat.rules import rule            # or: project_rule

@rule("MOAT-CUSTOM-001", "Human-readable rule name", (AGENT_SETTINGS,))
def check(target):
    yield Finding(rule_id=..., title=..., severity=..., path=target.path,
                  line=target.locate("needle"), impact=..., remediation=...,
                  evidence=...)
```

- Use `@project_rule` when the check needs every file at once — which is where
  the interesting risks live, since a per-file rule structurally cannot see a
  capability chain assembled across `.mcp.json` and `.claude/settings.json`.
- Rule ids are `MOAT-<FAMILY>-<NNN>`: `SECRET`, `PERM`, `SUPPLY`, `HOOK`,
  `INJECT`, `TRIFECTA` (plus `PARSE`, emitted by the scanner itself). Keep the
  family prefix meaningful — `tests/test_examples.py` asserts on the set of
  families the vulnerable example produces.
- New rule modules must be imported in `rules/load_all()` or they never register.
- `Target.locate(*needles)` recovers a line number by searching the raw text.
  Config formats give no source map; falling back to line 1 is expected.
- A rule that raises does not lose the other findings — `scanner.scan` catches
  and records it in `result.errors`. Don't rely on that; it is a safety net.

### The examples are tested documentation

`examples/vulnerable-agent-project` and `examples/hardened-agent-project` are the
same project configured badly and configured well, and
`examples/hardened-agent-project/README.md` is a line-by-line diff of the
changes. `tests/test_examples.py` asserts the vulnerable one trips every rule
family and stays CRITICAL, and the hardened one stays clean above LOW.

If you change a rule, expect these tests to move. Update the examples *and* the
prose that describes their output (both project READMEs quote finding counts)
rather than loosening the assertions.

## security_alert_system

### Architecture

```
  RSS feeds ──┐
              ├─► KeywordMatcher ─► dedupe (StateStore) ─► Notifier ─► Telegram
Telegram ch. ─┤                                              │
  POST /ingest┘                                              ├─► CameraRegistry (placeholder)
                                                             └─► Runtime ─► dashboard
```

`main.py` wires everything and owns graceful shutdown; `config.py` is the single
source of configuration; the module table in `security_alert_system/README.md`
lists the rest.

### Conventions and invariants

**Configuration is environment-only.** Everything goes through `Config.from_env()`
(with a hand-rolled, dependency-free `.env` loader that never overwrites a real
env var). Add a new setting as: a dataclass field with a default, a line in
`from_env`, a check in `validate()` if it can be set wrongly, and an entry in
`.env.example`. `validate()` returns a list of fatal problems and the process
refuses to start if it is non-empty — several of the security properties below
are enforced there, not at the call site.

**Run from the repository root.** Every command is `python -m
security_alert_system.…`; the package imports do not resolve from inside the
directory.

**Optional dependencies are imported lazily.** `anthropic` is imported inside
`run_monitor` only when `ASSISTANT_ENABLED`, and the voice providers likewise, so
the monitor runs with neither installed. Preserve that — do not hoist an optional
import to module scope.

**The ingest route is the only write path**, so its auth is unconditional: no
token means 503, never open. Its token must differ from the dashboard's, and
startup refuses if it does not.

**The dashboard is read-only and binds to `127.0.0.1`.** `DASHBOARD_HOST=0.0.0.0`
without `DASHBOARD_TOKEN` is rejected at startup — that combination publishes the
alert history to anyone who can reach the port. `/healthz` never requires the
token (container healthcheck). There is no web framework: `asyncio.start_server`
plus just enough HTTP/1.1.

**The assistant answers one chat only** (`TELEGRAM_ALERT_CHAT_ID`); anything else
is logged and dropped. It reads state through tools (`get_status`,
`recent_alerts`, `search_alerts`, `list_keywords`, `camera_status`), never from
the prompt, and tools return "nothing found" as a sentence so the model has
something concrete to report instead of filling the silence. Tools are declared
with `@beta_async_tool` inside `_build_tools`. The default model is
`claude-opus-5`.

**An alert is never delayed by an optional feature.** The raw alert is delivered
first and unmodified; assistant briefs arrive as a *separate* follow-up message,
and camera snapshot failures are caught and logged. Keep new features on that
side of the line.

**Failures are isolated.** One broken feed or a Telegram outage must not stop the
other sources. Network errors retry with exponential backoff; HTTP 429 is honoured
via `retry_after`; outgoing messages are throttled to ~1/sec per chat.

**Hebrew matching is subtle — change it with tests.** `keywords.py` normalises
niqqud, geresh/gershayim and RTL control marks, then compiles one regex per rule
handling attached prefixes (`בפיגוע`), inflectional suffixes (`פיגועים`),
multi-word phrases across line breaks, and word boundaries. Several rules are
hand-tuned against specific false positives with the reason in a comment beside
them (`טילים` takes no prefix or `מטילים` matches; `מטח` allows one trailing
letter or `מטחנה` matches). Feminine plurals are handled in the compiler, not
duplicated in the list. `tests/test_keywords.py` guards all of this, and it runs
without any dependency installed.

**`cameras.py` is deliberately inert.** Its module docstring is the real
documentation: the service runs in the cloud, cameras are on a private LAN, and
there is no route between them. Read it before touching camera code. RTSP
credentials are stripped from every log line via `CameraStream.safe_url`.

**Two different `Severity` enums exist in this repo** — `moat.models.Severity`
(`INFO=0 … CRITICAL=4`, five levels) and
`security_alert_system.keywords.Severity` (`INFO=1, ELEVATED, HIGH, CRITICAL`).
They are unrelated. Don't import across projects.

## Code style (both projects)

- `from __future__ import annotations` at the top of every module; modern
  built-in generics (`list[str]`, `str | None`).
- `@dataclass` for records; `IntEnum` / `Flag` for ordered or combinable states.
- **Module docstrings explain *why* the module exists and what threat it
  addresses**, not what the functions are named. Comments state a rationale a
  future reader could not reconstruct — a tuned regex, a security property, a
  deliberate omission. This is the strongest convention in the codebase; match it.
- Roughly 100 columns for code. Long prose strings wrap past it. No formatter or
  linter is configured — there is no black/ruff/mypy config, so don't reformat
  files wholesale.
- Google-style `Args:` sections where a function's parameters are non-obvious;
  most functions carry a one-line docstring instead.
- Tests are stdlib `unittest`, named as sentences
  (`test_read_only_git_subcommand_is_not_dangerous`). Neither suite touches the
  network or needs a key: Telegram, Anthropic and speech clients are all stubbed.

## Secrets

`.env`, `security_alert_system/state/` and `cameras.json` are gitignored. Never
commit a real token, and never write one into `.env.example`, a test fixture, or
a docstring. The credentials inside `examples/vulnerable-agent-project` are
deliberately fake fixtures for the secret-detection rules — leave them as they
are, and don't copy their shape into anything that isn't a fixture.

## Git

Development happens on feature branches; `main` is protected by the moat
workflow. Do not open a pull request unless explicitly asked.
