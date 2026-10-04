# Avid-aa

Independent security projects.

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

## [`veyra/`](veyra/README.md) — Veyra Security Brain

Unified cybersecurity posture management prototype: an Express API with
connectors for Google Workspace, Microsoft 365, AWS, Azure, GitHub and Slack
(simulated findings), a 0–100 risk score, prioritized remediation
recommendations, and a React + Tailwind dark-mode executive dashboard.

```bash
cd veyra && npm run setup && npm run dev   # http://127.0.0.1:5173
```

[Full documentation →](veyra/README.md)
