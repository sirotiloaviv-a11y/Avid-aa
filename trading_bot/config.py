"""Bot configuration.

Secrets are read from environment variables (or a local .env you export
yourself) and fall back to placeholders. Never hardcode real keys here.
"""

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name) or default


# --- Exchange API ---------------------------------------------------------
EXCHANGE_ID = _env("EXCHANGE_ID", "binance")
EXCHANGE_API_KEY = _env("EXCHANGE_API_KEY", "YOUR_EXCHANGE_API_KEY")
EXCHANGE_API_SECRET = _env("EXCHANGE_API_SECRET", "YOUR_EXCHANGE_API_SECRET")

# --- TradingView webhook --------------------------------------------------
TRADINGVIEW_WEBHOOK_SECRET = _env("TRADINGVIEW_WEBHOOK_SECRET", "YOUR_WEBHOOK_SECRET")
WEBHOOK_HOST = _env("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(_env("WEBHOOK_PORT", "8000"))

# --- Telegram -------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
# Dashboard buttons: Telegram POSTs updates to TELEGRAM_WEBHOOK_URL (public HTTPS
# URL of this server's /telegram/webhook) with TELEGRAM_WEBHOOK_SECRET in a header.
# Only TELEGRAM_CHAT_ID may use the buttons.
TELEGRAM_WEBHOOK_URL = _env("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET", "YOUR_TELEGRAM_WEBHOOK_SECRET")

# --- Risk limits (Prop Firm account) -------------------------------------
ACCOUNT_BALANCE = 1000000          # USD, starting balance of the funded account
MAX_DAILY_LOSS_PCT = 1.5           # % of ACCOUNT_BALANCE; trading halts once hit
MAX_RISK_PER_TRADE_PCT = 0.25      # % of ACCOUNT_BALANCE risked per trade
# Daily P&L + kill switch, persisted across restarts; resets at 00:00 UTC.
DAILY_STATE_FILE = _env("DAILY_STATE_FILE", str(Path(__file__).with_name("daily_state.json")))

# --- Execution ------------------------------------------------------------
# Paper-trade by default; set DRY_RUN=false only when you mean it.
DRY_RUN = _env("DRY_RUN", "true").lower() != "false"
