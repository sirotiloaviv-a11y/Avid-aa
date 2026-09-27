# trading_bot — prop firm trading bot (crypto + NQ futures)

Built to run unattended 24/7 on a VPS. **Module 1** is the core
infrastructure and the fail-safe risk manager; **Module 2** is Telegram alerts
and operator commands; **Module 3** is the web dashboard; **Module 4** is the
strategy engine, broker adapters and the trading loop. The execution and
strategy modules will call into the risk engine before every entry.

```
trading_bot/
├── config/config.py            .env → validated, typed Settings
├── risk_manager/
│   ├── risk_engine.py          RiskEngine (one per account) + RiskManager
│   ├── position_sizing.py      contracts / lots from stop distance
│   ├── news_guard.py           economic-calendar blackout
│   ├── controls.py             kill / resume / pause, shared by UI, Telegram, CLI
│   └── events.py               risk events published to subscribers
├── dashboard/
│   ├── state.py                statuses / journal → dashboard JSON (badges, totals)
│   ├── app.py                  routes, Basic auth, lockout, CSRF checks
│   ├── server.py               threaded HTTP server + live event stream (SSE)
│   └── static/                 index.html, app.css, app.js (no CDN, strict CSP)
├── strategies/
│   ├── base.py                 Strategy interface (candles/ticks → LONG/SHORT/FLAT)
│   ├── ema_cross.py            reference strategy: EMA cross, ATR stop, R:R target
│   ├── indicators.py, candles.py
│   └── executor.py             signal → risk engine → brokers, reconcile, flatten
├── brokers/
│   ├── base.py                 Broker interface (netted positions, bracket orders)
│   ├── paper.py                simulated fills, stops/targets on bar high/low
│   ├── tradovate.py            futures: REST (placeOSO) + chart WebSocket
│   ├── bybit.py                crypto: signed v5 REST + public kline WebSocket
│   ├── marketdata.py           simulated / replay / composite feeds
│   ├── streams.py              auto-reconnecting WebSocket stream
│   └── http.py                 JSON REST client (reads retried, orders never)
├── main.py                     TradingLoop + builders; `python -m trading_bot.main`
├── runtime.py                  BotRuntime: the one process that owns the state
├── telegram_bot/
│   ├── api.py                  Bot API client (urllib)
│   ├── formatter.py            events / statuses → Telegram HTML
│   ├── notifier.py             risk-event listener, background delivery
│   ├── commands.py             /status /news /halt /resume + polling
│   ├── scheduler.py            end-of-day summary
│   └── service.py              wires it all together
├── utils/
│   ├── logger.py               logs/bot.log, rotated, UTC timestamps
│   ├── state_store.py          SQLite state + risk-event audit trail
│   ├── time_utils.py           prop firm trading-day rollover
│   ├── process_lock.py         one bot process per state directory
│   └── websocket.py            minimal RFC 6455 client (stdlib)
├── logs/                       bot.log (git-ignored)
├── state/                      bot_state.db, calendar cache, KILL (git-ignored)
└── tests/
```

Python 3.10+. No third-party packages.

## Setup

```bash
cp trading_bot/.env.example trading_bot/.env    # then edit
python -m trading_bot check-config
python -m trading_bot status
```

## How the risk engine protects the account

| Guard | Rule | Lifts |
|---|---|---|
| Daily loss | equity ≤ day reference − `DAILY_LOSS_LIMIT_PCT` | at the next daily reset |
| Max drawdown | equity ≤ drawdown floor (static / trailing intraday / trailing EOD) | only by an operator (`clear-drawdown`) |
| Per-trade size | min(`RISK_PER_TRADE_PCT` of equity, `ROOM_USAGE_FRACTION` × room to the nearest floor − open risk) | — |
| Trade count | `MAX_TRADES_PER_DAY` | at the next daily reset |
| News | ±15 min around high-impact events in `NEWS_CURRENCIES` | when the window passes |
| Stale data | no account snapshot in `EQUITY_STALE_SECONDS` | on the next snapshot |
| Kill switch | `state/KILL` exists, or `halt ACCOUNT` | delete the file / `resume ACCOUNT` |

The engine **fails closed**. If it has no snapshot, stale equity, an unreadable
or unwritable state DB, no calendar data, or hits an internal error, it denies
the trade. When a limit is breached it reports `should_flatten=True` and fires
the `on_halt` callbacks. Closing positions is the execution layer's job.

The day reference is the higher of balance and equity at the first snapshot
after the reset (FTMO convention). The daily reset time defaults to 17:00
America/New_York (CME). Set `DAILY_RESET_TZ=UTC` and `DAILY_RESET_TIME=00:00`
for crypto firms that reset at midnight UTC.

## Trading (Module 4)

```
feed (WebSocket / simulator) ─► strategy ─► signal ─► ExecutionEngine
                                                        │  per account, in parallel:
                                                        ├─ already positioned? skip / reverse
                                                        ├─ RiskEngine.plan_trade (halts, news,
                                                        │  stale data, sizing for THIS account)
                                                        └─ broker.place_bracket (market + stop + target)
reconcile every ACCOUNT_POLL_SECONDS: balances → risk engine, closed positions →
P&L + reason (TP / SL / ...) → journal → Telegram + dashboard
halt (daily loss, max DD, kill switch) → flatten that account
news blackout starting → flatten everything (FLATTEN_ON_NEWS)
```

**Start in paper mode.** `TRADING_ENABLED=true`, leave every route on
`paper`, and `python -m trading_bot run`. Crypto uses real Bybit prices;
NQ uses simulated bars unless an account is routed to Tradovate. Watch the
dashboard for a few days before routing a real account.

**Brokers.**

| Broker | Asset | Environment | Notes |
|---|---|---|---|
| `paper` | both | local | fills at last price ± 1 tick; stops/targets from bar high/low (stop first if both) |
| `tradovate` | NQ/MNQ | demo unless `ENVIRONMENT=live` | Apex/Topstep-style accounts; `placeOSO` bracket, `isAutomated` set |
| `bybit` | USDT perps | testnet unless `ENVIRONMENT=live` | one-way mode, unified account; one API key per account |

The Tradovate and Bybit adapters are written against the published APIs and
tested against recorded request/response shapes, **not against the live
venues**. Run them on demo/testnet before a funded account. DXTrade isn't
implemented; add it by implementing the six methods of
`brokers/base.py:Broker`.

**Safety.**
- Orders are never retried automatically, because a timeout may have filled.
  If a matching position appears within 2 minutes, it is adopted with its stop.
- Positions the bot didn't open trigger an alert and are left alone.
- Stops and targets rest at the broker, so a crash doesn't leave a position
  unprotected. SIGINT/SIGTERM stop the loop without closing positions.
- Signals older than two bars (for example, after a feed stall) are ignored.
  After a WebSocket reconnect, bars already seen are dropped.
- Live trading refuses simulated or replayed market data.

**Adding a strategy.** Subclass `strategies.base.Strategy`, implement
`on_candle` (return a `Signal` with a stop, or `None`) and `warmup_bars`, and
return it from `main.build_strategy`.

## Using the risk engine from your own code

```python
from trading_bot.config import load_settings
from trading_bot.risk_manager import get_instrument
from trading_bot.runtime import BotRuntime
from trading_bot.utils import setup_logging

settings = load_settings()
setup_logging(settings.log_dir, settings.log_level)
runtime = BotRuntime(settings)        # takes state/bot.lock; builds engines,
runtime.start()                       # dashboard, Telegram and the control poller
risk = runtime.manager
risk.on_halt(lambda event: broker.flatten_all(event.account_id))   # execution layer

engine = risk["apex_nq_1"]
engine.update_account(balance=50_000, equity=49_870)                # on every broker update

plan = engine.plan_trade(get_instrument("NQ"), entry_price=20_000, stop_price=19_985)
if plan.approved:
    order = broker.submit(...plan.size.quantity...)
    engine.record_trade_opened(order.id, "NQ", float(plan.size.total_risk))
else:
    print(plan.decision.reasons)

# when the position closes:
engine.record_trade_closed(order.id, realized_pnl=-310.0)
```

## Telegram (Module 2)

1. Create a bot with [@BotFather](https://t.me/BotFather) and put the token in
   `TELEGRAM_BOT_TOKEN`.
2. Send the bot any message, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, and put `message.chat.id`
   in `TELEGRAM_CHAT_IDS`.
3. `python -m trading_bot telegram-test`, then `python -m trading_bot run`.

**Alerts** are sent automatically from risk-engine events:

| Event | Contents |
|---|---|
| Trade entry | symbol, LONG/SHORT, entry, SL, TP (with R:R), size, risk $ and %, account |
| Trade exit | symbol, exit price, P&L $ and %, reason (TP / SL / news halt / daily halt / manual), balance |
| Daily drawdown | at 50% and 80% of the daily limit (`DAILY_LOSS_WARN_LEVELS`), once per day |
| Halt | daily limit hit (100%), max drawdown, manual; says when trading resumes |
| Daily summary | 1 minute before the reset: trades, win rate, P&L per account and total |

Entry and exit alerts need the details passed to the engine:

```python
engine.record_trade_opened(order.id, "NQ", float(plan.size.total_risk),
                           direction=Direction.LONG, entry_price=20_000,
                           stop_price=19_985, take_profit=20_030,
                           quantity=plan.size.quantity)
engine.record_trade_closed(order.id, realized_pnl=-310.0, exit_price=19_985,
                           reason=ExitReason.STOP_LOSS, balance=49_690.0)
```

**Commands**, accepted only from `TELEGRAM_CHAT_IDS` (others are ignored silently):

| Command | Action |
|---|---|
| `/status` | P&L, open trades, daily and max drawdown for every account |
| `/news` | next 24h of high-impact events and whether entries are blocked |
| `/halt [reason]` | creates `state/KILL` and puts every account in manual halt (flatten) |
| `/resume` | removes `state/KILL` and clears manual halts; daily / max-DD halts stay |

Commands older than 2 minutes are not executed, and on first start any queued
backlog is skipped, so a `/resume` sent while the bot was down never runs late.

Alerts go through a background queue with retries, so Telegram being slow or
down never blocks the risk engine. `BotRuntime` starts the Telegram service in
the same process as the risk engines.

## Web dashboard (Module 3)

Set `DASHBOARD_PASSWORD` (12+ characters) and run `python -m trading_bot run`.
The dashboard is served on `DASHBOARD_HOST:DASHBOARD_PORT` (default
`127.0.0.1:8080`) from the same process as the risk engines.

- **Header:** overall status (ACTIVE / PARTIAL / HALTED), total equity, today's
  P&L in $ and %, and a countdown to the next high-impact news release.
- **Account cards:** balance, equity, today's P&L, daily-drawdown and
  max-drawdown bars, and a badge. Badges are ACTIVE, HIGH_RISK (≥ 80% of either
  limit), HALTED, PAUSED, or OFFLINE (no fresh account snapshot).
- **Trade history:** filter by account, status or symbol; click a column to
  sort. Below it is the activity log (halts, warnings, pauses, resets).
- **Controls:**
  - KILL SWITCH (with a confirmation dialog) halts and flattens every account.
  - RESUME clears the kill switch and manual halts.
  - The per-account switch *pauses* an account: no new entries, open positions
    are kept.
  - Daily-loss and max-drawdown halts can't be cleared from the UI.

Updates stream live over Server-Sent Events, and the page falls back to
polling if the stream drops.

**Security.**
- Basic auth on every page except `/healthz`. After 10 failed logins, that IP
  address is locked out for 5 minutes.
- Control requests must carry a custom header and a JSON body, so another
  website can't trigger them through your browser.
- A strict Content-Security-Policy; the page loads nothing from outside.

Basic auth sends the password with every request, so don't expose plain HTTP.
Keep `DASHBOARD_HOST=127.0.0.1` and use one of:

```bash
# HTTPS with automatic certificates (Caddy):
caddy reverse-proxy --from dashboard.example.com --to 127.0.0.1:8080
# or an SSH tunnel from your laptop, then open http://localhost:8080
ssh -L 8080:127.0.0.1:8080 you@your-vps
```

## One process owns the state

`python -m trading_bot run` (and, later, the trading loop) holds
`state/bot.lock` for as long as it runs. While it is held, CLI control
commands such as `halt`, `pause` and `kill` don't write account state
themselves; otherwise the running bot would overwrite them from memory. They
queue a request in SQLite, the bot applies it within about a second, and the
CLI prints the result. With no bot running, the CLI applies the change
directly. Requests older than 2 minutes are expired, not applied.

## Operator commands

```bash
python -m trading_bot run                    # dashboard + Telegram + controls (blocks)
python -m trading_bot kill "reason"          # emergency halt, all accounts
python -m trading_bot resume-all             # clear kill switch + manual halts
python -m trading_bot pause apex_nq_1        # block new entries, keep positions
python -m trading_bot unpause apex_nq_1
python -m trading_bot telegram-test          # send a test message
python -m trading_bot status                 # every account: P&L, floors, room, halts
python -m trading_bot news                   # blackout state + this week's events
python -m trading_bot halt apex_nq_1 "why"   # per-account kill switch (persists)
python -m trading_bot resume apex_nq_1
python -m trading_bot clear-drawdown apex_nq_1   # after the firm resets the account
touch trading_bot/state/KILL                 # block entries on every account now
```

## Before going live

- **Check the instrument specs** in `position_sizing.py` against your broker:
  tick value, commission, and minimum and maximum size.
- **Match your firm's rules.** Set `DAILY_LOSS_BASIS`, `MAX_DRAWDOWN_MODE`,
  `DRAWDOWN_LOCK_AT_INITIAL` and the reset time to match. Set your percentages
  *below* the firm's hard limits, because a stop can fill past its price.
- **Keep `state/` on persistent disk.** Deleting `bot_state.db` resets today's
  loss tracking.
- **Check the news feed.** The ForexFactory JSON feed is unofficial and
  rate-limited, so the bot caches it. For extra safety, keep
  `NEWS_CALENDAR_FILE` pointed at a hand-maintained list of FOMC and CPI dates.

## Tests

```bash
python -m unittest discover -s trading_bot/tests -t . -v
```
