# Avid-aa

Independent projects, each in its own directory.

## [`aiworkspace/`](aiworkspace/README.md) — local AI chat workspace

A single-user, localhost-only chat workspace with streamed replies, saved
conversation history, and Hebrew/English (RTL/LTR) support. Phase 1 of a
broader workspace; runs in a clearly labelled demo mode without an API key.

```bash
python -m aiworkspace   # http://127.0.0.1:8765/
```

No dependencies. [Full documentation →](aiworkspace/README.md)

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
