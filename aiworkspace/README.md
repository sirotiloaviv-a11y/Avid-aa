# aiworkspace — local AI chat workspace (phase 1.1)

A single-user chat workspace that runs on your own machine. Phase 1 is one
complete flow: create a conversation, send a message, watch the reply stream
in, stop it, and reopen, rename or delete saved conversations. Hebrew (RTL) and
English (LTR) are both first-class, per paragraph, with code blocks always
left-to-right.

Standard library only: a Python HTTP server, SQLite, and a plain-JavaScript UI.
No `pip install`, no `npm install`, no build step.

> **Local prototype.** No authentication. The server refuses to bind to
> anything but loopback. Public or multi-user deployment requires real
> authentication, per-user data, and server-side ownership checks on every
> conversation and message route first.

## Start

Requires Python 3.10+ and a modern browser. From the repository root:

```bash
python -m aiworkspace            # http://127.0.0.1:8765/
python -m aiworkspace --port 9000
```

Without an API key it starts in **demo mode**: every reply begins with
"Demo mode — this is a simulated reply, not live AI", is stored with a
`simulated` flag, is tagged *Simulated* in the UI, and a banner stays on
screen. Sending `/demo-error` in demo mode shows the error state.

### Live replies (Anthropic)

```bash
cp aiworkspace/.env.example aiworkspace/.env
# edit aiworkspace/.env and set ANTHROPIC_API_KEY=...
python -m aiworkspace
```

The startup line says `live provider: anthropic, model: …` and the header badge
reads *Live · model*. `aiworkspace/.env` is git-ignored. The key stays in the
server process: it is not sent to the browser, not included in `/api/status`,
and not logged.

## Configuration

All settings are environment variables, optionally in `aiworkspace/.env`
(real environment variables win). See [`.env.example`](.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | empty | Enables the live adapter. |
| `AIWS_PROVIDER` | `auto` | `auto`, `anthropic` or `demo`. |
| `AIWS_MODEL` | `claude-opus-5` | Any Messages API model ID. |
| `AIWS_ANTHROPIC_FALLBACKS` | `off` | Opt-in beta: `default` adds server-side refusal fallback (`fallbacks` + `anthropic-beta: server-side-fallback-2026-07-01`). When `off`, neither is sent. |
| `AIWS_MAX_RETRIES` | `2` | Automatic retries per message (0–3), only for rejected requests; see below. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | API base URL. |
| `AIWS_HOST` / `AIWS_PORT` | `127.0.0.1` / `8765` | Loopback only. |
| `AIWS_DB_PATH` | `aiworkspace/.data/workspace.sqlite3` | SQLite file. |
| `AIWS_MAX_MESSAGE_CHARS` | `16000` | Per message. |
| `AIWS_MAX_OUTPUT_TOKENS` | `16000` | `max_tokens` per reply, including thinking tokens. |
| `AIWS_MAX_CONTEXT_CHARS` | `200000` | History sent to the model; oldest turns dropped first. |
| `AIWS_REQUEST_TIMEOUT_S` | `120` | Hard limit for one reply, including retries and retry waits. |
| `AIWS_RATE_LIMIT_PER_MINUTE` | `20` | Messages per minute. |

### Output cap and cost

`AIWS_MAX_OUTPUT_TOKENS` (default 16,000) is sent as `max_tokens`. It is a
ceiling, not a target: you pay for tokens actually generated. With
`claude-opus-5`, thinking is adaptive by default and thinking tokens count
toward `max_tokens` and are billed as output, so a low cap risks replies cut
off mid-answer (shown as *Incomplete — hit the output token limit*).

Worst case per message, at the list price in Anthropic's reference
(claude-opus-5: $5 input / $25 output per million tokens; check current
pricing): 16,000 output tokens ≈ **$0.40**, plus input. Input grows with the
conversation, up to `AIWS_MAX_CONTEXT_CHARS` (200,000 characters, roughly
50k–100k tokens depending on language) ≈ $0.25–0.50. Typical short exchanges
cost far less. The rate limit (20 messages/minute) bounds the pathological
case. Lower `AIWS_MAX_OUTPUT_TOKENS`, `AIWS_MAX_CONTEXT_CHARS` or the rate
limit to tighten spend.

### Retries are bounded

Per user message the adapter makes at most `1 + AIWS_MAX_RETRIES` HTTP
attempts (hard cap 4), inside the `AIWS_REQUEST_TIMEOUT_S` deadline, with
waits capped at 10 s. It retries **only** when the API answered 429, 5xx or 529
before streaming, or the connection was never established (DNS failure,
connection refused). It never retries after any response body has started,
after a timeout, or after an ambiguous network error, because the API may
already have generated (and billed) that request. The UI's *Retry* button is
the only other way a message is re-sent, and it is always a user action.

### Streaming and reply status

* Text arrives as `text_delta` events and is shown as it streams.
* Thinking blocks (`thinking_delta`, `signature_delta`) are neither displayed
  nor stored; they only keep the connection alive. No `thinking` parameter is
  sent, so the model's default applies.
* The served model ID (`message_start`), input tokens and output tokens
  (`message_delta.usage`) are stored per reply and shown under live replies.
* Status: `complete` only for `end_turn` or `stop_sequence`. Any other stop
  reason (`max_tokens`, `refusal`, `model_context_window_exceeded`,
  `pause_turn`, or a new value) is stored as `incomplete` and labelled.
  Stopped by the user → `cancelled`. A failure or a stream that ends without
  `message_stop` → `error`, with any partial text kept and labelled
  *Partial reply — incomplete*.
* A live failure is shown as an error. The app never substitutes demo output.

## Checks

```bash
python -m unittest discover -s aiworkspace/tests -t .   # 71 tests, no network
ruff check aiworkspace && ruff format --check aiworkspace
mypy --strict aiworkspace --exclude aiworkspace/tests
cd aiworkspace && tsc -p jsconfig.json && eslint static && cd ..   # if installed
# Browser flow in demo mode, with desktop + mobile screenshots (needs playwright):
NODE_PATH=$(npm root -g) node aiworkspace/tests/browser_check.cjs /tmp/aiws-shots
```

The provider tests use canned HTTP responses. They verify request shape and
error handling, not the live API.

### Live smoke test (opt-in, paid)

```bash
python -m aiworkspace.live_smoke                         # dry run: plan + cost bound
python -m aiworkspace.live_smoke --confirm-paid-request  # sends 2 short requests
```

One Hebrew question, then a follow-up answerable only from context. Prints the
returned model ID, status, stop reason and token usage per turn; never prints
the key. Uses a throwaway database. Exit 3 means BLOCKED (no key configured).

## How it fits together

```
static/            index.html, app.js (UI state), markdown.js (safe renderer), i18n.js, styles.css
server.py          routing, Host/CSRF checks, security headers, SSE reply stream
chat.py            context building and one reply's lifecycle (stream, cancel, persist)
providers/base.py  TextProvider interface, stream events, ProviderError
providers/anthropic.py   Messages API adapter (raw HTTPS + SSE)
providers/demo.py        labelled simulated adapter
store.py           SQLite: conversations, messages
validation.py, ratelimit.py, config.py
```

A reply is a `POST /api/conversations/{id}/messages` answered with
`text/event-stream` events `start`, `delta`, then `done` or `error`. Stop sends
`POST …/cancel`; closing the tab also cancels. The partial reply is saved as
`cancelled`. Replies are checkpointed every two seconds, so a crash keeps what
was generated and marks it interrupted on the next start.

### Safety measures in this phase

* Loopback bind, Host-header allowlist (DNS-rebinding), custom header plus
  Origin check on every state-changing request (CSRF).
* Strict CSP (`script-src 'self'`, no inline script). Model output is rendered
  by `markdown.js`, which only creates DOM nodes via `textContent`; only
  `http(s)`/`mailto` links become links. ESLint forbids `innerHTML` and friends.
* Validation of every input; limits on message size, request body, output
  tokens, context size, request duration and request rate; one active reply per
  conversation.
* Logs contain method, route and status only; never message text or titles.
* No code execution, tools, or shell access for the model.

## Limitations

* Single user, no authentication, loopback only. Anyone with a shell on the
  machine can read the SQLite file; it is not encrypted.
* The Anthropic adapter uses raw HTTPS because this project avoids
  dependencies and package registries were unreachable when it was written.
  The official SDK (`anthropic`) is the better long-term client; the adapter
  interface makes that a local swap.
* No token counting: the context budget is in characters.
* No edit/regenerate, search, attachments or export yet.
* Live generation has **not** been verified end to end: no API key was
  available during development. Run the live smoke test above to verify.

## Adding capabilities later

Each new modality should be a new server-side interface next to
`TextProvider`, with its own adapter(s), limits and a storage shape, and only
get a UI control once it works end to end.

* **Images** — an `ImageProvider.generate(prompt, size) -> ImageResult`, results
  stored as files under `.data/` with a `attachments` table referencing
  messages; image *input* to chat is a content-block change inside the text
  adapter (the Messages API accepts image blocks).
* **Voice** — speech-to-text and text-to-speech providers behind the composer
  (record → transcript → normal message; reply → audio stream). Browser capture
  needs microphone permission handling.
* **Video** — asynchronous jobs: a `jobs` table, a worker, and polling or SSE
  progress events, because generation takes minutes.
* **Research** — server tools such as web search/fetch in the Messages API, or
  a retrieval layer; answers need citations stored alongside messages.
* **Coding tools / task execution** — tool use with an explicit allowlist, a
  sandbox that is not the host (container or remote), per-call user approval,
  and an audit log. Nothing in phase 1 executes generated code.

Also required before any shared deployment: authentication, per-user
ownership checks on every route, secrets management, HTTPS, persistent rate
limits per user, and a privacy policy for stored conversations.
