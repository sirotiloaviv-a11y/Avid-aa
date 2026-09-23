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

## [`market_info/`](market_info/README.md) — stock and crypto information prototype (Hebrew)

A local market information dashboard in right-to-left Hebrew: watchlist,
charts, news, event calendar and factual information alerts. Runs on fictional
demo data by default; an optional market-data mode shows delayed / end-of-day
prices from Alpha Vantage (stocks) and CoinGecko (crypto) using keys you keep
in a local `.env`. No trading account, no recommendations.

```bash
cd market_info && npm start   # http://localhost:5173
```

No npm dependencies. [Full documentation (Hebrew) →](market_info/README.md)
