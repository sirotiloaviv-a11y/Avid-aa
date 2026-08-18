# Bridges — sources that live outside the monitor

The monitor pulls RSS and Telegram itself. Everything else pushes in through
one authenticated route:

```
POST http://127.0.0.1:8080/ingest
Authorization: Bearer $INGEST_TOKEN
Content-Type: application/json

{"source": "וואטסאפ · שכונה", "text": "...", "kind": "whatsapp", "id": "wamid.ABC"}
```

| field | required | meaning |
|---|---|---|
| `source` | yes | Shown on the alert and the dashboard. Name it so you know where it came from at 3am. |
| `text` | yes | The message. Runs through the same 60-keyword Hebrew filter. |
| `kind` | no | Groups sources on the dashboard: `whatsapp`, `scrape`, `camera`… |
| `id` | no | The bridge's own id. Used for dedupe, so a bridge restart replaying its backlog alerts once. |
| `url` | no | Link included in the alert. |
| `timestamp` | no | Unix seconds, when the message was originally posted. |

The response tells you what happened, so a bridge can log its own hit rate:

```json
{"accepted": true, "matched": true, "alerted": true,
 "severity": "CRITICAL", "phrases": ["פיגוע"], "reason": ""}
```

**Why bridges run as separate processes.** They are the fragile and risky
parts: a WhatsApp reader can get an account banned, a scraper breaks when a
site changes its markup, a camera agent sits on a home network that reboots.
Out of process, any of them can crash or be killed without touching the thing
that has to keep running — and the monitor keeps alerting from RSS and Telegram
the whole time a bridge is down.

Keep bridges on the same host as the monitor so the ingest port never leaves
`127.0.0.1`. If one must run elsewhere, put it behind a TLS reverse proxy —
never expose the ingest port directly.

## Testing the pipe before writing a bridge

```bash
curl -s -X POST http://127.0.0.1:8080/ingest \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"בדיקה","text":"שמעתי פיצוץ חזק ליד הצומת","kind":"test"}'
```

A matching push arrives in Telegram as a normal alert and appears on the
dashboard under its source name.
