# Avid-aa

Three independent projects.

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

## [`trading_dashboard/`](trading_dashboard/README.md) — multi-account trading console

A Streamlit desk that routes one order to a master account and copies it out to
sub-accounts spread across several email sessions, with a live TradingView-style
chart and a per-account drawdown kill switch. Market data and broker responses
are simulated, so it runs with no broker credentials.

```bash
pip install -r trading_dashboard/requirements.txt
streamlit run trading_dashboard/app.py
```
[Full documentation →](trading_dashboard/README.md)
