# Avid-aa

Two independent security projects.

## [`moat/`](moat/README.md) — security scanner for AI agent configuration

Audits what your AI agents are actually allowed to do. Scans MCP server
definitions, permission allowlists, hooks, subagents and skills for hardcoded
credentials, unreviewed code execution, prompt-injection surface, and
data-exfiltration paths that no single line of config reveals.

```bash
python -m moat .
```

No dependencies. Emits SARIF for GitHub code scanning.
[Full documentation →](moat/README.md)

## [`security_alert_system/`](security_alert_system/README.md) — Hebrew security-alert monitor

Monitors Hebrew-language news and Telegram sources for security events, matches
them against a keyword ruleset that handles Hebrew prefixes, suffixes and
niqqud, and dispatches alerts.

## [`fitness-platform/`](fitness-platform/README.md) — Hebrew fitness & nutrition SaaS

A production-shaped platform with three experiences behind one brand: a women's
track, a men's track, and an admin console. The split between tracks is enforced
server-side at every layer, not in the UI.

```bash
cd fitness-platform && python3 -m fitness_platform seed && python3 -m fitness_platform serve
```

Python 3.11 standard library only — no runtime dependencies.
[Full documentation →](fitness-platform/README.md)
