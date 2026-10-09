"""Bot configuration.

Settings come from environment variables, then from trading_bot/.env, then
fall back to placeholders. Never hardcode real keys here.
"""

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes.
    Real environment variables always win over the file."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(Path(__file__).with_name(".env"))


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
# "paper" simulates every order; only "live" sends orders to the exchange.
ENVIRONMENT = _env("ENVIRONMENT", "paper").strip().lower()
if ENVIRONMENT not in ("paper", "live"):
    raise ValueError(f"ENVIRONMENT must be 'paper' or 'live', got {ENVIRONMENT!r}")
DRY_RUN = ENVIRONMENT != "live"
