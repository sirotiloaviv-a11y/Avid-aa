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

## [`datascope/`](datascope/README.md) — real-time market dashboard

Live prices for US stocks and crypto in one Hebrew (RTL) dashboard: streaming
price cards, intraday stats, live price and volume charts, a movers ticker, and
an alert engine that raises desktop notifications — price targets, percentage
spikes and volume surges — carrying the full asset name and symbol.

```bash
cd datascope && npm start
```

Crypto streams from Binance over a public WebSocket and US stocks come through
a narrow local Yahoo proxy, so it works with no signup; a free Finnhub key
upgrades stocks to a real-time stream. Browser-only and dependency-free: no
backend, no database, and nothing stored anywhere but your own browser.
[Full documentation →](datascope/README.md)
