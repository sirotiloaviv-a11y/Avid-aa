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

## [`shopify-sanans-theme/`](shopify-sanans-theme/README.md) — סנאנס, עיצוב סופרמרקט אונליין ל-Shopify

סקשנים, סניפטים ו-CSS מותאמים לתבנית Dawn: Hero עם חיפוש, קטגוריות, דיל יומי,
כרטיסי מוצר עם הוספה מהירה לעגלה ותגיות מבצע. כולל מדריך התקנה ומיקרו-קופי בעברית.
