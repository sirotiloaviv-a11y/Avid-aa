# trading_bot — prop firm trading bot (crypto + NQ futures)

Built to run unattended 24/7 on a VPS. **Module 1** (this code) is the core
infrastructure and the fail-safe risk manager. It does not place orders yet.
The execution and strategy modules will call into it before every entry.

```
trading_bot/
├── config/config.py            .env → validated, typed Settings
├── risk_manager/
│   ├── risk_engine.py          RiskEngine (one per account) + RiskManager
│   ├── position_sizing.py      contracts / lots from stop distance
│   └── news_guard.py           economic-calendar blackout
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

## Operator commands

```bash
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
