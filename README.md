# Avid-aa

Independent projects: two security tools and a prop firm trading bot.

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

## [`trading_bot/`](trading_bot/README.md) — prop firm trading bot (crypto + NQ)

Autonomous trading bot for prop firm accounts. Module 1 is the fail-safe risk
layer: daily loss and trailing drawdown halts that survive restarts, position
sizing from stop distance, and a news blackout around high-impact releases.
