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

## [`crypto_alerts/`](crypto_alerts/README.md) — real-time crypto trading alerts

Streams exchange candles over ccxt.pro websockets, runs an RSI + volume +
support/resistance strategy on each closed candle, sizes the trade so a stop-out
loses exactly a fixed % of equity, checks order-book depth for slippage, and
sends the execution plan to Telegram. It sends urgent Pushover and sound alerts
for high-conviction setups, and has a live dashboard for monitoring and risk
adjustment.

```bash
DRY_RUN=true python -m crypto_alerts
```
