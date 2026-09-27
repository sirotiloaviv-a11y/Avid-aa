# trading_bot — prop firm trading bot (crypto + NQ futures)

Built to run unattended 24/7 on a VPS. **Module 1** is the core
infrastructure and the fail-safe risk manager; **Module 2** is Telegram alerts
and operator commands. It does not place orders yet. The execution and
strategy modules will call into the risk engine before every entry.

```
trading_bot/
├── config/config.py            .env → validated, typed Settings
├── risk_manager/
│   ├── risk_engine.py          RiskEngine (one per account) + RiskManager
│   ├── position_sizing.py      contracts / lots from stop distance
│   └── news_guard.py           economic-calendar blackout
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
│   └── time_utils.py           prop firm trading-day rollover
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

## Using it from the trading loop

```python
from trading_bot.config import load_settings
from trading_bot.risk_manager import RiskManager, build_news_guard, get_instrument
from trading_bot.utils import StateStore, setup_logging

settings = load_settings()
setup_logging(settings.log_dir, settings.log_level)
store = StateStore(settings.state_db_path)
risk = RiskManager.from_settings(
    settings, store,
    news_guard=build_news_guard(settings.news),
    kill_switch_path=settings.state_db_path.parent / "KILL",
)
risk.on_halt(lambda event: broker.flatten_all(event.account_id))   # module 2

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
down never blocks the risk engine. Run the Telegram service in the same
process as the risk engines (`TelegramService(...).start()`); `run` does that
for now, until the trading loop exists.

## Operator commands

```bash
python -m trading_bot run                    # Telegram alerts + commands (blocks)
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
