# Avid-aa

Two independent security projects, plus a video promo.

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

## [`ai-king-promo/`](ai-king-promo/setup.py) — "מלך ה-AI נחשף" Remotion promo

A 20-second vertical (1080x1920) breaking-news identity-reveal video in
Remotion/TypeScript. One script scaffolds the whole project:

```bash
python3 ai-king-promo/setup.py --install   # writes the project + installs deps
cd ai-king-promo && npm start               # preview; `npm run build` renders the MP4
```
