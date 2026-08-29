# Hardened example

The same project as [`../vulnerable-agent-project`](../vulnerable-agent-project),
configured the way moat recommends.

```console
$ python -m moat examples/hardened-agent-project
  2 low
$ echo $?
0
```

## What changed

| Vulnerable | Hardened | Why |
| --- | --- | --- |
| `"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_…"` | `"${GITHUB_TOKEN}"` | the file stops being a credential |
| `npx -y server-github` | `server-github@2025.4.8` | the registry no longer decides what code runs on your machine at launch |
| `--dsn postgresql://app:pw@db/prod` | server removed | a credential in `args` is visible to every local process |
| `defaultMode: bypassPermissions` | removed | the confirmation prompt is the last control before a poisoned instruction becomes an action |
| `Bash(*)` | `Bash(git status:*)`, `Bash(git diff:*)` | read-only subcommands cannot push |
| `WebFetch` | `WebFetch(domain:docs.python.org)` | pinning removes both the ingress and the egress |
| `additionalDirectories: ["~", "/etc"]` | removed | no reason for the agent to reach SSH keys |
| `Stop` hook POSTing the transcript to a vendor | removed | an automatic, unreviewed egress channel |
| `PreToolUse` hook interpolating `$CLAUDE_TOOL_INPUT` | removed | model-controlled text in a shell string is a command injection |
| MCP server over `http://` with a poisoned description | removed | cleartext transport, and instructions aimed at the model |
| Subagent with no `tools:` line | `tools: Read, Grep, Glob` | it no longer inherits the parent's full authority |

Nothing here is exotic. Every change is a narrower version of what was already
written.

## The part worth studying: `issue-triage`

```yaml
tools: Read, Grep, mcp__github__get_issue
```

This subagent reads issue text — which is written by whoever opened the issue,
so it is untrusted input by definition — and it reads private source code. Two
of the three capabilities.

What it deliberately does not have is any way to send data outward. It writes
its triage note to a local file for a human to read. So an instruction injected
into an issue body has nothing to do with what the agent learns: there is no
channel out.

moat reports this as `MOAT-TRIFECTA-002` at `low` — not a defect, but a note
that this principal is one grant away from a leak path, so adding
`mcp__github__create_comment` later is a security decision rather than a
convenience one.

That is the whole idea: you rarely remove an agent's usefulness to secure it.
You separate the capabilities so no single principal holds all three.

## The remaining `low` on the main agent

The main agent can read private data and, through the filesystem MCP server,
write it — but nothing in its configuration ingests attacker-controlled text.
Two of three again, and the missing one is the one that matters most.
