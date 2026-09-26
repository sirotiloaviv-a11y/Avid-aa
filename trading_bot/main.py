"""Entry point: a FastAPI server that receives TradingView webhook alerts.

Run with:  python main.py
"""

import hmac
import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from execution import OrderExecutor
from risk_manager import RiskManager
from telegram_reporter import TelegramReporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trading_bot")

app = FastAPI(title="Prop Firm Trading Bot")
risk = RiskManager()
executor = OrderExecutor()
reporter = TelegramReporter()


class Signal(BaseModel):
    """Expected TradingView alert JSON body."""

    secret: str
    symbol: str
    side: str          # "buy" or "sell"
    entry: float
    stop: float


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "dry_run": executor.dry_run, "daily_pnl": risk.daily_pnl}


@app.post("/webhook")
def webhook(signal: Signal) -> dict:
    if not hmac.compare_digest(signal.secret, config.TRADINGVIEW_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")

    if not risk.can_trade():
        reporter.send(f"Signal ignored: daily loss limit reached ({signal.side} {signal.symbol})")
        return {"status": "blocked", "reason": "daily loss limit"}

    size = risk.position_size(signal.entry, signal.stop)
    order = executor.market_order(signal.symbol, signal.side, size)
    reporter.send(f"{signal.side.upper()} {size:.4f} {signal.symbol} @ ~{signal.entry} (stop {signal.stop})")
    return {"status": "submitted", "order": order}


def main() -> None:
    log.info(
        "Starting bot: balance=%s, daily loss limit=%.2f%%, dry_run=%s",
        config.ACCOUNT_BALANCE, config.MAX_DAILY_LOSS_PCT, config.DRY_RUN,
    )
    uvicorn.run(app, host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT)


if __name__ == "__main__":
    main()
