# Security Alert System — מערכת התראות ביטחוניות

Monitors Israeli news RSS feeds and Telegram channels, filters for Hebrew
security keywords (`פיגוע`, `צבע אדום`, `אירוע ביטחוני`, …), and pushes an
immediate alert to your personal Telegram chat.

Built to run unattended in a cloud container. Includes a documented
placeholder layer for wiring in local RTSP cameras later.

---

## Quick start

```bash
cd security_alert_system
pip install -r requirements.txt
cp .env.example .env          # then edit .env

# 1. create a bot with @BotFather, put the token in .env
# 2. send your bot any private message, then:
python -m security_alert_system.main --chat-id     # prints your chat id
# 3. put that id in TELEGRAM_ALERT_CHAT_ID

python -m security_alert_system.main --check       # validate config
python -m security_alert_system.main --test        # send a test alert
python -m security_alert_system.main               # run (monitor + dashboard)
```

Run every command from the **repository root** (the directory containing
`security_alert_system/`), so the package imports resolve.

---

## How it works

```
  RSS feeds ──┐
              ├─► KeywordMatcher ─► dedupe (StateStore) ─► Notifier ─► your Telegram chat
Telegram ch. ─┘                                              │
                                                             ├─► CameraRegistry (placeholder)
                                                             └─► Runtime ─► status dashboard
```

| File | Role |
|---|---|
| `main.py` | CLI, wiring, graceful shutdown |
| `config.py` | env/`.env` configuration, defaults, validation |
| `keywords.py` | Hebrew-aware matching, severity levels |
| `alerts.py` | the alert record + Telegram HTML rendering |
| `sources/rss.py` | feed polling with conditional GET |
| `sources/telegram_channels.py` | `getUpdates` long-polling listener |
| `telegram_api.py` | Bot API client: retries, rate limits |
| `notifier.py` | delivery, throttling, snapshot attachment |
| `state.py` | dedupe + Telegram offset, atomic writes |
| `monitoring.py` | alert history + per-source health, for the dashboard |
| `dashboard.py` | dependency-free HTTP status page |
| `assistant.py` | conversational AI layer (Claude + tools) |
| `voice.py` | speech in / speech out, swappable providers |
| `ingest.py` | the one authenticated write route for outside sources |
| `cameras.py` | **RTSP placeholder layer** — read its docstring |

---

## Hebrew keyword matching

A plain `in` check fails on Hebrew news text. The matcher handles:

- **Attached prefixes** — `בפיגוע`, `והפיגוע` both match `פיגוע`.
- **Inflectional suffixes** — `פיגועים` matches `פיגוע`.
- **Niqqud, geresh/gershayim, and RTL control marks** are normalised away.
- **Multi-word phrases across line breaks** — `צבע אדום` matches even when the
  words are split by a newline after HTML stripping.
- **Word boundaries** — `בצבע אדום כהה` does *not* trigger the `צבע אדום` rule.

Each rule carries a severity (`INFO` / `ELEVATED` / `HIGH` / `CRITICAL`); an
alert takes the highest severity among its matches.

The default set is 60 phrases: 17 `CRITICAL`, 28 `HIGH`, 15 `ELEVATED`.

A few rules are tuned by hand to avoid collisions, and the reason is in a
comment beside each: `טילים` takes no attached prefix (otherwise `מטילים`, an
unrelated verb, matches), and `מטח` allows only one trailing letter (otherwise
`מטחנה` matches). Feminine nouns are handled in the compiler rather than
duplicated in the list — `רקטה` covers `רקטות`, because the final ה is
*replaced*, not appended, and no trailing-letter window can reach it.

Override the whole default set via `KEYWORDS` in `.env`:

```
KEYWORDS=פיגוע:CRITICAL,"צבע אדום":CRITICAL,אירוע ביטחוני:CRITICAL,אזעקה:HIGH
```

Quoting a phrase disables prefix/suffix tolerance (exact match only) — useful
for fixed phrases like `צבע אדום` where fuzzy matching just adds noise.

---

## AI assistant

A conversational layer over the monitor — message the bot in your private chat
and it answers, in Hebrew, about live system state. Named `קארן` by default
(`ASSISTANT_NAME`), after the Spider-Man suit AI.

```
you:   מה המצב?
קארן:  שקט בשעתיים האחרונות. חמישה מקורות תקינים, ישראל היום מחזיר 503 כבר 40 דקות.

you:   היה משהו באזור הצפון היום?
קארן:  שתי התראות: אזעקות ב-14:20 ופיקוד העורף ב-14:35, שתיהן מ-ynet.
```

**It reads state through tools, not from the prompt** — `get_status`,
`recent_alerts`, `search_alerts`, `list_keywords`, `camera_status`. That is the
design point, not an implementation detail: every factual claim it makes comes
from a tool result on the current run, so it reports what the system actually
saw rather than what sounds plausible. The tools return "nothing found" as a
sentence rather than empty context, so the model has something concrete to
report instead of filling the silence.

**It answers one chat only.** Private messages are routed to it only from
`TELEGRAM_ALERT_CHAT_ID`; anything else is logged and dropped. Without that
check anyone who finds the bot could hold a conversation on your API budget and
read your alert history back through the tools.

**Proactive briefs.** After an alert at `ASSISTANT_BRIEF_ON_SEVERITY` or above,
it adds one line of context ("third tonight from the same area") as a *separate*
message — the raw alert always lands first and unmodified, and a slow or failed
model call can never delay or replace it.

Commands: `/start` for help, `/reset` to clear the conversation. Both are
handled locally without calling the model.

```bash
ASSISTANT_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...
```

The `anthropic` import is lazy, so the monitor runs without the package
installed as long as the assistant is off.

---

## Sources: what it reads, and how to add more

| Source | How | Status |
|---|---|---|
| News sites | RSS, conditional GET every 60s | built in |
| Telegram channels | `getUpdates`, bot must be admin | built in |
| Telegram groups | same, **privacy mode must be off** — see below | built in |
| WhatsApp groups | bridge → ingest route | `bridges/whatsapp_bridge.md` |
| Sites with no RSS | scraper → ingest route | write a bridge |
| Cameras | agent → ingest route, or the connectors in `cameras.py` | placeholder |

**Telegram groups need privacy mode off.** A bot added to a group sees nothing
by default — Telegram hides every message that is not a command or a reply to
the bot, so the monitor sits there matching nothing and looking broken. In
BotFather: `/setprivacy` → pick the bot → **Disable**, then **remove and re-add
the bot to the group** (the setting applies when it joins). Group alerts carry
the sender name as well as the group, because in a conversation "who said it"
is part of judging a report.

**Everything else pushes in through one route.** `POST /ingest` with a bearer
token runs the same keyword matcher, the same dedupe, the same severity ladder,
and produces the same alert with the same assistant context and dashboard row.
A new source is a new bridge script, not a new branch inside the monitor.

```bash
curl -s -X POST http://127.0.0.1:8080/ingest \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"וואטסאפ · שכונה","text":"שמעתי פיצוץ ליד הצומת","kind":"whatsapp"}'
```

Bridges run as separate processes on purpose — they are the fragile and risky
parts (a WhatsApp reader risks a ban, a scraper breaks on markup changes, a
home agent reboots), and out of process any of them can die without touching
the monitor. Contract and examples: `bridges/README.md`.

The ingest route is the **only** write path in the system, so its auth is
unconditional: no token configured means the route returns 503, never open. Its
token must differ from the dashboard's, and startup refuses if it does not.

**WhatsApp specifically has no legitimate API for reading groups** — not on any
tier. The unofficial path runs as a linked device on your own account and risks
a permanent ban on your number. I did not put that code in the repo; the
tradeoff and a working sketch are in `bridges/whatsapp_bridge.md` so the choice
is yours to make explicitly.

---

## Voice — talking to it with headphones on

You hold the mic button in Telegram, speak Hebrew, and the answer comes back as
a voice note that auto-plays in your ear. Nothing to install on the phone;
Telegram already carries both directions.

```
you (hold mic) ──► Telegram ──► transcribe ──► assistant ──► speak ──► voice note
```

**The format detail that makes it work.** Telegram voice messages are OPUS in
an OGG container, and `sendVoice` requires the same going back. An MP3 is
accepted but renders as a music file — no waveform, no auto-play, useless in a
pocket. OpenAI's speech endpoint emits opus directly, so the round trip needs
no ffmpeg and no transcoding.

**Reply medium follows the question.** `VOICE_REPLY_MODE=match` (the default)
speaks back only when you spoke first. A text reply is useless with headphones
in a mall; a voice reply to something typed at a desk is worse.

**Providers are swappable.** Claude does no speech, so this needs a second
provider. The `Transcriber` / `Speaker` interfaces in `voice.py` are the whole
integration surface:

| `VOICE_PROVIDER` | Transcribe | Speak | Notes |
|---|---|---|---|
| `openai` | whisper-1 | gpt-4o-mini-tts | Fast, good Hebrew. ~$0.006/min in, ~$0.015/1k chars out. |
| `local` | faster-whisper on your host | OpenAI, if a key is set | No audio leaves the machine. Slower; first run downloads the model. |

Local transcription with no local synthesis is deliberate — offline Hebrew TTS
is poor enough that a bad voice is worse than no voice, so it answers in text.

**Every failure still delivers.** Synthesis failure falls back to text, a
transcription failure says so rather than guessing, and an unintelligible clip
never reaches the model. Stranger voice notes are dropped before the download,
so nothing unauthorised is ever paid for.

```bash
VOICE_ENABLED=true
OPENAI_API_KEY=sk-...
```

---

## Running it 24/7

```bash
cp security_alert_system/.env.example .env    # then fill it in
docker compose up -d
docker compose logs -f
```

`restart: unless-stopped` in `docker-compose.yml` is what makes it actually
24/7 — the container returns after a crash, a Docker daemon restart, and a host
reboot. Dedupe state and alert history live in a named volume, so a redeploy
does not re-alert on whatever is currently in the feeds.

The dashboard stays bound to `127.0.0.1` inside the container and is not
published. Reach it with `docker compose exec alerts curl -s localhost:8080/api/status`
or an SSH tunnel.

---

## Status dashboard

Runs alongside the monitor and shows what is being watched, which sources are
healthy, and every alert that has fired.

```
GET /             the dashboard (Hebrew, RTL, auto-refreshes every 10s)
GET /api/status   the same data as JSON
GET /healthz      "ok" — for a container healthcheck, never requires the token
```

```bash
python -m security_alert_system.main             # monitor + dashboard
python -m security_alert_system.main --dashboard # dashboard only, no polling
```

It is dependency-free — `asyncio.start_server` plus just enough HTTP/1.1 — so
the service doesn't carry a web framework it would only use for one page. There
are no write routes.

**Access.** It binds to `127.0.0.1` by default, which inside a cloud container
means "reachable only from inside the container". Use `docker exec`, an SSH
tunnel, or your platform's port-forward:

```bash
ssh -L 8080:127.0.0.1:8080 you@host      # then open http://localhost:8080
```

Setting `DASHBOARD_HOST=0.0.0.0` without `DASHBOARD_TOKEN` is **rejected at
startup** — that combination publishes your alert history to anyone who can
reach the port. With a token set, pass it as `?token=…` or
`Authorization: Bearer …`.

Alert history persists to `state/alerts.json` (bounded by `ALERT_HISTORY_SIZE`),
so a restart doesn't wipe the visible record.

---

## Telegram channels — an important limitation

**A bot can only read channels where it is an administrator.** The Bot API
gives no way to subscribe to an arbitrary public channel; that needs a *user*
account over MTProto (Telethon/Pyrogram), which means logging in as yourself.

Two supported paths:

| Situation | What to do |
|---|---|
| You own / admin the channel | Add the bot as admin, list it in `TELEGRAM_CHANNELS`. Works directly. |
| Public channel you don't control | Bridge it to RSS and add the URL to `RSS_FEEDS`. |

Public channels have a web view at `https://t.me/s/<channel>`, and bridges such
as RSSHub expose that as a feed:

```
RSS_FEEDS=https://rsshub.app/telegram/channel/<channel_name>
```

Same keyword filter, same alerts, no account risk. (Public RSSHub instances are
rate-limited and go down; self-host it if you depend on this path.)

`TELEGRAM_CHANNELS` accepts `@username`, a bare username, or a numeric
`-100…` id. Leave it empty and the listener accepts posts from any channel the
bot has been added to.

---

## Cameras (placeholder)

`cameras.py` is deliberately inert by default. Its module docstring is the real
documentation — read it before wiring anything up. The short version:

> **This script runs in the cloud. Your cameras are on a private LAN. There is
> no route between them.** An RTSP URL like `rtsp://192.168.1.50/stream` will
> simply time out from a cloud container, no matter how correct it is.

Options, best first:

1. **On-prem push agent** (`CAMERA_CONNECTOR=push_inbox`) — a script at home
   grabs JPEGs over the LAN and uploads them to a directory this service reads.
   Nothing at home is exposed to the internet. **Recommended.**
2. **Mesh VPN** (Tailscale / WireGuard) — join the container to your network,
   then `CAMERA_CONNECTOR=ffmpeg` works unchanged.
3. **Outbound reverse tunnel** (Cloudflare Tunnel, `ssh -R`, frp).
4. **Port-forwarding a camera to the internet** — don't.

Define streams in `cameras.json` (see `cameras.example.json`) or the `CAMERAS`
env var, set `CAMERAS_ENABLED=true`, and snapshots are attached automatically to
any alert at or above `CAMERA_SNAPSHOT_ON_SEVERITY`. Camera failures are caught
and logged — they can never block or delay the text alert.

Credentials embedded in an RTSP URL are stripped from every log line
(`CameraStream.safe_url`).

---

## Operational notes

- **First run** indexes whatever is already in the feeds *without* alerting
  (`PRIME_WITHOUT_ALERTING=true`), so you don't get a flood at startup.
- **Dedupe state** lives in `STATE_PATH`. Cloud containers are disposable —
  point it at a mounted volume, or accept a small burst of repeats after a
  redeploy.
- **Polling** uses `If-None-Match` / `If-Modified-Since`, so unchanged feeds
  cost one cheap 304. Don't set `RSS_POLL_SECONDS` below 15.
- **Rate limiting** — outgoing messages are throttled to ~1/sec per chat, and
  HTTP 429 is honoured via `retry_after`.
- **Failures are isolated** — one broken feed, or a Telegram outage, does not
  stop the other sources. Network errors retry with exponential backoff.
- `SIGINT`/`SIGTERM` flush state and shut down cleanly.

### Deployment

```bash
docker build -t security-alerts security_alert_system/
docker run -d --restart=unless-stopped \
  --env-file security_alert_system/.env \
  -v alertstate:/app/security_alert_system/state \
  security-alerts
```

The container needs no inbound ports — it only makes outbound HTTPS calls.

### This is a monitoring aid, not a warning system

It reports what the news says, on a delay of however long the source takes to
publish. **It is not a substitute for פיקוד העורף / Home Front Command alerts.**
Use the official app for actual sirens.

---

## Tests

```bash
python -m unittest discover -s security_alert_system/tests -t .
```

135 tests, no network and no keys of any kind required — the Telegram,
Anthropic and speech clients are all stubbed.
Covers Hebrew normalisation, affix and feminine-plural matching, the tuned
false-positive guards, feed→alert flow, dedupe across restarts, HTML escaping,
the camera severity gate, source-health transitions, history persistence, the
dashboard's routes and token auth (over a real socket on an ephemeral port), and
the assistant's tools, history bounds, failure paths and access check, and
the voice round trip including every fallback path, and the ingest
route's auth, dedupe, rate limiting and malformed-input handling.
