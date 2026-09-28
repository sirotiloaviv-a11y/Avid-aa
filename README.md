# Avid-aa

Two independent security projects, plus a video project.

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

## [`ai-king-trailer/`](ai-king-trailer/README.md) — "THE AI KING REVEALED" trailer

A 60-second cinematic trailer built with Remotion (React → MP4), with cyber-underworld
intro, mask-to-face reveal, action montage and title card.

```bash
cd ai-king-trailer && npm install && npm start
```
