# trading_bot — Prop Firm algorithmic trading bot ($1,000,000 account)

Receives TradingView webhook alerts, sizes positions against prop-firm risk
limits, executes through ccxt, and reports to Telegram.

| File | Role |
|---|---|
| `main.py` | Entry point — FastAPI server (`POST /webhook`, `GET /health`) |
| `config.py` | API keys, webhook secret, Telegram, risk limits |
| `risk_manager.py` | Position sizing + daily stop-loss (1.5% = $15,000) |
| `telegram_reporter.py` | Sends updates to Telegram |
| `execution.py` | Order execution via ccxt (dry-run by default) |

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
