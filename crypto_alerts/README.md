# crypto_alerts: real-time crypto trading alerts

Watches exchange candles in real time, runs a strategy on every **closed**
candle, sizes the trade to a fixed fraction of your equity, and sends the full
execution plan to Telegram. Before an alert goes out, it checks the live order
book for slippage. High-conviction setups also go out as urgent push
notifications with sound. A live web dashboard shows the whole system and lets
you change equity and risk per trade while it runs. You place the order
yourself. The system never trades and never needs trading permissions.

```
🟢 LONG · BTC/USDT · 15m
⚡ RSI oversold + 3.4x Volume Surge + Support bounce

🎯 Entry: 63,912.40 – 64,050.00
      don't chase above 64,050.00
🛑 Stop Loss: 63,410.20 (−1.00%)
      swing low − 0.2 ATR
✅ Take Profit: 65,649.50 (+2.50%)
⚖️ Risk/Reward: 1 : 2.5

💰 Position Size
• Size: $500,547.05 (0.50x equity)
• Units: 7.81494217 BTC
• Loss at SL: $5,000.00 (0.50% of equity)
• Profit at TP: $12,500.00

💧 Liquidity: ✅ ~0.012% slippage for full size (spread 0.002% · limit 0.1%)

📊 Trigger Reasons
• RSI oversold (27.3 < 30)
• 3.4x volume surge vs 20-candle average
• Bounce off support 63,520.00 (swing low)
```

## Quick start

```bash
pip install -r crypto_alerts/requirements.txt
cp crypto_alerts/.env.example crypto_alerts/.env   # then fill in Telegram token + chat id
DRY_RUN=true python -m crypto_alerts                # alerts print to the console first
python -m crypto_alerts                             # live
```

The dashboard is at <http://127.0.0.1:8765/> while the process runs.

Tests use only the standard library (the exchange and bot are stubbed):

```bash
python -m unittest discover -s crypto_alerts/tests -t .
```

## Architecture

```
crypto_alerts/
├── config.py         Settings from env/.env, typed and validated (all errors reported at once)
├── market_data.py    ccxt.pro websocket / REST feed → closed-candle stream, reconnect + backfill
├── indicators.py     RSI, ATR (Wilder), EMA/SMA, volume ratio, swing highs/lows
├── strategy.py       Strategy base class + RsiVolumeReversalStrategy template
├── risk_manager.py   Stop loss, take profit, sizing, order-book slippage + liquidity guard
├── notifiers.py      Notification type, Pushover + sound channels, fan-out dispatcher
├── telegram_bot.py   Alert formatting (HTML + compact push text), Telegram channel
├── state.py          In-memory runtime state: feed health, prices, alert log, risk changes
├── dashboard.py      Live web dashboard + JSON API (stdlib HTTP server, same process)
├── main.py           AlertEngine wiring, per-symbol tasks, urgency rule, graceful shutdown
└── tests/            146 unit, pipeline and real-socket dashboard tests
```

```
                         ┌──────────── on_tick / on_feed_state ────────────┐
                         │                                                 ▼
exchange ─ws/REST─▶ MarketDataFeed ─closed candles─▶ indicators ─▶ Strategy   RuntimeState ◀─ Dashboard
                         ▲                                           │           ▲      (GET /api/state,
                         │ fetch_order_book                          ▼           │       POST /api/risk)
                         └──────────────────────────────────── RiskManager ──────┤            │
                                                          (size, liquidity guard)│            │
                                                                     ▼           │            │
          Telegram / urgent chat ◀─┐                             AlertEngine ────┘            │
          Pushover (priority+sound) ◀─ AlertDispatcher ◀─ Notification (urgent?)  ◀── update_risk
          local sound / console   ◀─┘
```

Each symbol runs in its own asyncio task on one shared exchange connection.
Alerts go through a queue, and every channel sends concurrently with its own
retries. A slow or failing channel never delays market data or the other
channels.

## How it decides

**Closed candles only.** A candle counts as closed once the next one has
opened. Evaluating a forming candle gives alerts whose RSI and volume change a
minute later, so this system never does it. Stale candles (for example after a
long outage) are skipped because they are no longer actionable.

**Long trigger** (template): RSI < 30, volume ≥ 2.5× the average of the
previous 20 candles, and the candle's low comes within `SR_TOLERANCE_ATR` of a
prior confirmed swing low, then closes above it with a bullish reaction (a
green close, or a lower wick at least half the candle's range).
**Short** is the mirror image at a swing high. Every threshold is in `.env`.

**Stop loss** (`STOP_MODE`):
- `atr`: entry ∓ `ATR_STOP_MULTIPLIER` × ATR
- `swing`: beyond the invalidation level (the further of the wick and the
  S/R level) by `SWING_BUFFER_ATR` × ATR
- `hybrid` (default): the swing stop, widened to `MIN_STOP_ATR` if it sits
  inside normal noise, and replaced by the ATR stop if it is further than
  `MAX_STOP_ATR`

**Take profit**: entry ± `RISK_REWARD_RATIO` × stop distance.

**Position size**: `units = ACCOUNT_EQUITY × RISK_PER_TRADE_PCT / 100 / |entry − stop|`.
A fill at the reference entry that hits the stop loses exactly the budget
($5,000 on $1M at 0.5%). Three settings adjust this, and each can only make
the realised risk *smaller*. The alert shows the resulting figure:
- `FEE_RATE_PCT`: the budget includes entry and exit fees
- quantity is rounded **down** to the exchange's lot step
- `MAX_LEVERAGE` caps notional on very tight stops, and the alert flags when it applies

The entry zone lies only on the favourable side of the signal price, so any
fill inside it risks at most the budget. The alert tells you not to chase
beyond it.

## Liquidity guard (slippage protection)

A market order for the planned size walks the order book, so its average
price is worse than mid. Just before dispatch, the engine fetches the book
(`ORDER_BOOK_DEPTH` levels per side), simulates that fill for the calculated
size, and measures the **expected slippage vs mid**. The spread is included,
because you pay half of it on entry.

| `LIQUIDITY_ACTION` | If slippage > `MAX_SLIPPAGE_PCT` (default 0.1%) or the visible book can't fill the size |
|---|---|
| `warn` (default) | Alert is sent with a **⚠️ THIN BOOK** section: expected slippage, the largest size that fits the limit, and the loss at SL including slippage |
| `reduce` | Size shrinks to the largest quantity whose average fill stays within the limit, rounded down to the lot step. Risk falls below budget, and the alert says so |
| `filter` | The alert is dropped. The dashboard's log records it as `filtered` with the reason |

The largest size that fits is solved exactly, not by searching: whole levels
priced within the limit are taken, and at the first level beyond it
`q = (limit·units − cost) / (price − limit)` gives the partial quantity at
which the average fill equals the limit.

If the order book can't be fetched, the alert still goes out, marked
*"slippage unknown"*. A flaky endpoint shouldn't cost you a valid signal.
Contract markets are converted to base units using the contract size.

## Urgent alerts (high conviction)

Each signal lists its **conviction factors**, which are plain rules rather than
an opaque score, so the alert can say exactly why it was flagged:

- **Extreme RSI**: `EXTREME_RSI_MARGIN` points past the threshold (≤ 20 / ≥ 80 by default)
- **Extreme volume**: `EXTREME_VOLUME_FACTOR` × the spike multiplier (≥ 5x by default)
- **With the trend**: a long above the slow EMA, a short below it

An alert is **urgent** when it has at least `URGENT_MIN_FACTORS` (default 2)
factors *and* the liquidity check passed (`ok` or `reduced`). A trade you
can't fill cleanly shouldn't wake you up. Urgent alerts get a
`🚨🔥 HIGH CONVICTION` header and go to every channel:

| Channel | Setting | Behaviour |
|---|---|---|
| Telegram | always on | Every alert. With `TELEGRAM_QUIET_NORMAL_ALERTS=true`, normal alerts arrive silently and only urgent ones make a sound |
| Telegram urgent chat | `TELEGRAM_URGENT_CHAT_ID` | Urgent alerts are copied here. Bots can't choose a sound per message, so give this chat its own notification sound in the Telegram app. That gets you a distinct alarm |
| Pushover | `PUSHOVER_APP_TOKEN` + `PUSHOVER_USER_KEY` | Compact alert with `PUSHOVER_SOUND` at `PUSHOVER_PRIORITY`. Priority `2` (emergency) repeats every 60s for 30 min until acknowledged, so it gets through Do Not Disturb |
| Local sound | `SOUND_COMMAND` | Runs a player on the host (no shell), e.g. `afplay …` / `paplay …`. The terminal bell in `DRY_RUN` |

## Web dashboard

Served from inside the alert process at `DASHBOARD_HOST:DASHBOARD_PORT`
(default `127.0.0.1:8765`) and refreshed every 2 s:

- **Risk metrics**: equity, risk %, $ at risk per trade, R:R, leverage cap,
  and the slippage limit. For the last 24h: alerts, urgent alerts, alerts
  filtered by liquidity, and total risk if every alert had been taken and stopped out
- **Adjust risk**: change `ACCOUNT_EQUITY` and `RISK_PER_TRADE_PCT` live. The
  next alert uses the new values. The same bounds as `.env` are enforced
  (risk ≤ 5%). Every change is logged and announced on Telegram. Changes are
  runtime-only, so update `.env` to keep them after a restart
- **Symbols**: feed state (live / reconnecting / stale / stopped), live
  price, last closed-candle RSI, volume ratio and ATR, alert and reconnect counts, last error
- **Alert log**: sent, urgent, filtered, suppressed and discarded signals, with
  prices, size, risk, slippage, conviction and liquidity outcome
- **Delivery**: sent/failed count and last error per channel

`GET /api/state` returns the same data as JSON. `GET /healthz` is a liveness check.

**Why not Streamlit:** Streamlit runs as a separate process, so a live risk
change would need a database or IPC to reach the engine. In-process, the
dashboard reads the engine's live state directly and a change applies to the
very next alert. It is a small `asyncio` HTTP server with no dependencies.

**Security:** this page can change position sizing, so it is locked down:

- It binds to `127.0.0.1` by default. For remote access use an SSH tunnel
  (`ssh -L 8765:127.0.0.1:8765 host`).
- A non-loopback `DASHBOARD_HOST` is refused unless `DASHBOARD_TOKEN` is set.
  Open `/?token=…` once and the token becomes an HttpOnly, SameSite=Strict
  cookie. Put TLS in front if you expose it.
- Risk changes need a per-process CSRF token in a custom header and a
  same-origin `Origin`.
- The Host header is checked (loopback names only when no token is set), which
  blocks DNS rebinding.
- The page has a strict CSP with per-response nonces and `frame-ancestors 'none'`.
- All data is rendered with `textContent`, so an exchange error message can
  never inject markup.

## Reliability

- Network errors, exchange downtime and silent websockets (`STREAM_TIMEOUT_SECONDS`)
  trigger reconnects with exponential backoff and jitter, plus a REST backfill
  so indicators are never computed across a gap.
- Unrecoverable errors (unknown or delisted symbol, bad API key) stop only the
  affected symbol and send a Telegram notice. The others keep running.
- An exception while evaluating a candle is logged and skipped. It never kills
  the stream.
- Telegram sends are retried and honour flood-control `retry_after`. Permanent
  errors (such as a bad chat id) are not retried. Pushover retries 5xx/429
  errors but not other 4xx errors.
- Each channel is isolated. The dashboard's Delivery table shows per-channel failures.
- Per symbol/direction cooldown (`ALERT_COOLDOWN_MINUTES`) prevents alert spam.
- SIGINT/SIGTERM drain queued alerts and close the exchange connection cleanly.

## Adding a strategy

Subclass `Strategy`, implement `evaluate(symbol, timeframe, frame) -> Signal | None`
using the series in `IndicatorFrame`, and pass it to `AlertEngine` in
`main.run`. Set `invalidation_level` to where the idea is wrong. The risk
manager derives the stop, target and size from it.

## Caveats

- Perpetual symbols use ccxt's unified form, e.g. `BTC/USDT:USDT` on Bybit or
  Binance with `MARKET_TYPE=swap`. Inverse (coin-margined) contracts are rejected.
- Units are in the base asset (BTC, ETH, ...), which is what the Binance and
  Bybit apps take as quantity.
- Slippage is estimated from the visible book at alert time. Books move, and
  hidden or iceberg liquidity isn't counted. Treat it as a guide to how
  aggressively to enter, not a quote.
- The bundled strategy is a template to build on, not a tested edge. Paper
  trade it (`DRY_RUN=true`) before you size real money from it.
