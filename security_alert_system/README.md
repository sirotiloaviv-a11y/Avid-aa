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

64 tests, no network and no bot token required — the Telegram client is stubbed.
Covers Hebrew normalisation, affix and feminine-plural matching, the tuned
false-positive guards, feed→alert flow, dedupe across restarts, HTML escaping,
the camera severity gate, source-health transitions, history persistence, and
the dashboard's routes and token auth (over a real socket on an ephemeral port).
