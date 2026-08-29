# moat

**Your AI agents hold keys to the kingdom. moat tells you which doors are open.**

An agent's real permissions do not live in your code. They live in five small
JSON and Markdown files that nobody reviews: which MCP servers start on your
machine, which tools are pre-approved, which shell commands fire automatically,
and what each subagent inherits. Those files decide whether a poisoned web page
can read your `.env` and post it to a stranger.

moat reads them and tells you.

```console
$ moat .

 CRITICAL  subagent 'triage' can read private data, ingest untrusted text and send it out
          .claude/agents/triage.md:1  [MOAT-TRIFECTA-001]
          This is a working exfiltration path that needs no vulnerability: read
          private data (`Read`) → ingest attacker-controlled text
          (`mcp__github__get_issue`) → send data outward (`mcp__slack__post_message`).
          Any content the agent reads — a web page, a dependency README, a
          pull-request comment — can carry instructions that walk it, and the agent
          has standing permission for every step.
          fix: Break the chain for this principal. Usually the cheapest cut is
          egress: pin web access to known hosts and remove blanket network commands.
```

No dependencies, no account, no telemetry. It reads files and prints findings.

---

## Install and run

```bash
pip install moat-scanner
moat .                      # scan the current project
moat ~/Library/Application\ Support/Claude   # scan a desktop host config
```

Or with nothing installed at all:

```bash
git clone https://github.com/sirotiloaviv-a11y/avid-aa && cd avid-aa
python -m moat /path/to/project
```

Requires Python 3.10+. That is the entire dependency list — deliberately. A
scanner that warns you about unpinned supply-chain risk should not arrive with
forty transitive packages of its own.

---

## What it finds

### The one that matters: capability chains

Every other check here is a lint. This one is an analysis.

Reviewing an agent's permissions one line at a time misses the actual risk,
because no single grant is the vulnerability. The vulnerability is a
**combination**. An agent that can

1. reach **private data** — your files, your repos, your database,
2. ingest **untrusted input** — a web page, an issue, an email, a dependency's
   README, and
3. **send data outward** — an HTTP request, a Slack message, a commit,

can be made to leak, with no exploit and no bug. Somebody writes instructions
into content the agent was always going to read, and the agent — behaving
exactly as designed — reads a secret and sends it somewhere. This is the
*lethal trifecta*, and you cannot patch it, because nothing is broken.

moat builds a capability model of each **principal** (the main agent, and each
subagent separately), across every config file in the project, and reports the
principals that hold all three. It names the specific tool that supplies each
capability, so the finding is a chain you can break rather than a score.

It is deliberately precise in both directions:

| Grant | Verdict | Why |
| --- | --- | --- |
| `Bash` | all three | it can `cat` a secret, `curl` a hostile page and POST the result |
| `Bash(git status:*)` | private data only | a read-only subcommand cannot push |
| `Bash(curl:*)` | ingest + send | it reaches the network, not your files |
| `WebFetch` | ingest + send | any URL in, any URL out |
| `WebFetch(domain:docs.python.org)` | nothing | pinning is the mitigation — flagging it would punish the fix |
| `mcp__github__get_issue` | private data + ingest | issue text is written by whoever opened it |
| `mcp__github__create_issue` | private data + send | |
| `mcp__unknown-server` | all three | an unrecognised server is an unbounded grant |

It reads `permissions.deny` and `disabledMcpjsonServers` and subtracts what they
actually remove — and only what they actually remove. Denying three write tools
out of a server's twenty does not clear the capability, and moat will not
pretend it does.

It classifies a server by the **package it launches**, not the alias in your
config, because a server nicknamed `docs` may be the filesystem server.

### Everything else

| Family | What it catches |
| --- | --- |
| `MOAT-SECRET` | live credentials pasted into `.mcp.json` / settings — vendor patterns plus an entropy fallback, with placeholders and `${ENV}` references excluded. Flags keys in `args` separately, because those are visible to every process on the machine. |
| `MOAT-PERM` | `bypassPermissions`, `Bash(*)`, unrestricted `WebFetch`, filesystem grants reaching `~` or `/etc`, subagents that silently inherit every tool |
| `MOAT-SUPPLY` | `npx -y package` with no version pin (whatever the registry serves at launch runs with your environment), `curl \| sh` installers, plain-HTTP MCP endpoints, whole-environment passthrough |
| `MOAT-HOOK` | hooks that interpolate model-controlled data into a shell string (a command injection with a very short path from an attacker's text to your shell), hooks that open a network channel, hooks that run destructive commands |
| `MOAT-INJECT` | **tool poisoning** — instructions hidden in an MCP tool description, which the model reads and the user approving the tool never sees; **invisible Unicode**, decoded and printed so you can read what was hidden; skills that fetch remote content and then act on it |

Full catalogue: `moat --list-rules`.

---

## A report you can send someone

```bash
moat . --format html -o report.html
```

One self-contained file: no server, no build step, and **no network request when
it is opened** — a security report gets forwarded and opened on machines that
are not yours, so it has no business phoning a font CDN. It opens with the
capability chain for every principal drawn out, then the findings, filterable by
severity and text.

The report renders strings that came out of configuration files, and a poisoned
tool description is exactly what `MOAT-INJECT-002` exists to find — so every
value is escaped at the boundary, hidden Unicode is rendered as a visible name
rather than passed through, and the page's script never writes markup. A scanner
that turned a finding into an exploit against the person reading the report
would be worse than no scanner.

## In CI

moat emits SARIF, so findings land as annotations on the pull request rather
than in a log nobody opens.

```yaml
- run: pip install moat-scanner
- run: moat . --exclude 'examples/*' --format sarif -o moat.sarif --fail-on never
- uses: github/codeql-action/upload-sarif@v3
  with: { sarif_file: moat.sarif }
- run: moat . --fail-on high     # exit 1 blocks the merge
```

Adopting on an existing repo with a backlog:

```bash
moat . --write-baseline .moat-baseline.json   # accept today's findings
moat . --baseline .moat-baseline.json         # only new ones fail
```

Fingerprints exclude line numbers, so reformatting a config does not resurrect
findings your team already triaged.

```
moat [PATH] [--format text|json|sarif|html] [-o FILE] [--fail-on LEVEL]
            [--min-severity LEVEL] [--baseline FILE] [--write-baseline FILE]
            [--disable RULE] [--exclude GLOB] [--list-rules]
```

Exit `0` clean, `1` findings at or above `--fail-on` (default `high`), `2` usage error.

---

## See it work

```bash
python -m moat examples/vulnerable-agent-project   # 22 findings, 10 critical
python -m moat examples/hardened-agent-project     # 2 informational; exit 0
```

The two directories are the same project, configured badly and configured well.
[`examples/hardened-agent-project/README.md`](../examples/hardened-agent-project/README.md)
is a line-by-line diff of what changed and why — the most useful page here if
you are trying to fix your own setup.

Both are covered by the test suite, so the documentation cannot drift away from
what the tool does.

---

## Design notes

**Unknown means dangerous.** An MCP server moat does not recognise is scored as
holding every capability. Failing open would let any unrecognised server hide a
trifecta, which is the failure mode that makes a scanner worth ignoring.

**Every finding states its consequence and its fix.** A finding that only names
a rule makes the reader do the research. The test suite asserts that every
finding carries a non-trivial `impact` and `remediation`.

**Credentials are redacted everywhere.** A report is a file that gets pasted
into chat. The suite asserts no detected secret appears in any output field.

**False positives are tested as hard as true positives.** Every rule has a
negative case. A scanner that cries wolf gets muted, and a muted scanner is
worth nothing.

## Extending it

A rule is a function that yields findings:

```python
from moat.models import AGENT_SETTINGS, Finding, Severity
from moat.rules import rule

@rule("MOAT-CUSTOM-001", "Internal policy: no production database servers", (AGENT_SETTINGS,))
def no_prod_db(target):
    for name, config in target.data.get("mcpServers", {}).items():
        if "prod" in str(config.get("args", "")):
            yield Finding(
                rule_id="MOAT-CUSTOM-001",
                title=f"Server '{name}' points at production",
                severity=Severity.HIGH,
                path=target.path,
                impact="An agent mistake in this session is a production incident.",
                remediation="Point the server at a read replica.",
            )
```

Use `@project_rule` instead when the check needs every file at once, as the
trifecta analysis does.

## Tests

```bash
python -m unittest discover -s tests -t . -v    # 136 tests, no dependencies
```

## License

MIT.
