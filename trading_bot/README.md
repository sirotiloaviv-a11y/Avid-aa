# trading_bot — Prop Firm algorithmic trading bot ($1,000,000 account)

Receives TradingView webhook alerts, sizes positions against prop-firm risk
limits, executes through ccxt, and reports to Telegram.

| File | Role |
|---|---|
| `main.py` | Entry point — FastAPI server (`POST /webhook`, `POST /telegram/webhook`, `GET /health`) |
| `config.py` | API keys, webhook secret, Telegram, risk limits |
| `risk_manager.py` | Position sizing + daily stop-loss (1.5% = $15,000) |
| `telegram_reporter.py` | Telegram messages, daily summary, dashboard keyboard |
| `execution.py` | Order execution via ccxt (dry-run by default) |
| `daily_state.json` | Runtime: daily P&L, trade stats, kill switch (git-ignored) |

## Setup

```bash
cd trading_bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in, then: set -a; source .env; set +a
python main.py
```

`DRY_RUN` is on unless you explicitly set `DRY_RUN=false`.

## TradingView alert body

```json
{"secret": "<TRADINGVIEW_WEBHOOK_SECRET>", "symbol": "BTC/USDT", "side": "buy", "entry": 60000, "stop": 59000}
```

## Telegram dashboard

Send `/menu` (or `/start`) to the bot to get the dashboard:

```
[ 📊 PNL יומי ]        [ 🔓 פוזיציות פתוחות ]
[ 🛡️ סטטוס סיכון ]     [ 🚨 KILL-SWITCH חירום ]
```

- **PNL** — today's P&L, the $1,000,000 base balance, and equity.
- **POSITIONS** — open positions (symbol, side, size, entry, unrealized P&L).
- **RISK** — daily loss vs. the 1.5% ($15,000) limit, and kill-switch status.
- **KILL-SWITCH** — asks for confirmation, then blocks trading until 00:00 UTC
  and market-closes every position.

`/summary` sends today's report; the previous day's report is sent
automatically at 00:00 UTC.

Setup: the server must be reachable over public HTTPS. Set
`TELEGRAM_WEBHOOK_URL=https://<your-host>/telegram/webhook` and a random
`TELEGRAM_WEBHOOK_SECRET` (letters, digits, `_`, `-`); the bot registers the
webhook on startup. Only `TELEGRAM_CHAT_ID` can use the buttons. Both webhook
endpoints refuse requests until their secrets are set.

## Tests

```bash
cd trading_bot && python -m unittest -v
```
