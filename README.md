# Avid-aa

Independent local-first projects.

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

## [`datascope/`](datascope/README.md) — educational historical-data explorer

Imports a historical price CSV, validates it strictly, and explains the
descriptive statistics in Hebrew: symbol selector, date range, price and volume
charts, sortable table, and CSV/text exports.

```bash
cd datascope && npm start
```

Browser-only and dependency-free — no server, no account, no API key, and
nothing leaves the page. Educational tool: no live data, no signals, no
recommendations.
[Full documentation →](datascope/README.md)
