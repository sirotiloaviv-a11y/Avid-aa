# Avid-aa

Independent projects.

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

## [`wolt-for-pros/`](wolt-for-pros/README.md) — on-demand tradesperson platform

"Wolt for electricians and plumbers": clients book a licensed pro and track them
live on a map. Pros work from a prepaid fee wallet (Stripe top-ups) that holds
the fee when they accept a job and charges it when the client's completion code
is verified. Underpriced closes are flagged and repeat offenders auto-suspended.
Express + Prisma + Socket.io backend, Next.js + Tailwind + Leaflet frontend.
