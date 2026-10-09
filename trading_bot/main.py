"""Entry point: FastAPI server for TradingView alerts and the Telegram dashboard.

Run with:  python main.py
"""

import asyncio
import hmac
import html
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import config
import telegram_reporter as tg
from execution import OrderExecutor
from risk_manager import RiskManager
from telegram_reporter import TelegramReporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trading_bot")

ROLLOVER_CHECK_SECONDS = 30

executor = OrderExecutor()
reporter = TelegramReporter()


def _send_day_end_summary(stats: dict) -> None:
    reporter.send_daily_summary(
        stats["pnl"], stats["total_trades"], stats["win_rate"], stats["current_drawdown"], date=stats["date"]
    )


risk = RiskManager(
    state_file=config.DAILY_STATE_FILE,
    executor=executor,
    alert=reporter.send,
    on_day_end=_send_day_end_summary,
)


def _secret_matches(given: Optional[str], expected: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), expected.encode())


def _is_placeholder(secret: str) -> bool:
    return not secret or secret.startswith("YOUR_")


async def _rollover_loop() -> None:
    """Apply the 00:00 UTC reset (and send the day's summary) even when idle."""
    while True:
        await asyncio.sleep(ROLLOVER_CHECK_SECONDS)
        try:
            await asyncio.to_thread(risk.check_rollover)
        except Exception:
            log.exception("Rollover check failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.TELEGRAM_WEBHOOK_URL and not _is_placeholder(config.TELEGRAM_WEBHOOK_SECRET):
        reporter.set_webhook(config.TELEGRAM_WEBHOOK_URL, config.TELEGRAM_WEBHOOK_SECRET)
    reporter.send_dashboard(
        "🤖 <b>הבוט הופעל | Bot started</b>"
        + (" <i>(DRY RUN)</i>" if executor.dry_run else "")
        + "\nבחר פעולה | Choose an action:"
    )
    task = asyncio.create_task(_rollover_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Prop Firm Trading Bot", lifespan=lifespan)


# --- TradingView -----------------------------------------------------------------

class Signal(BaseModel):
    """Expected TradingView alert JSON body."""

    secret: str
    symbol: str
    side: str          # "buy" or "sell"
    entry: float
    stop: Optional[float] = None   # required in practice: RiskManager rejects trades without it


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "environment": config.ENVIRONMENT,
        "dry_run": executor.dry_run,
        "daily_pnl": risk.daily_pnl,
        "kill_switch_active": risk.kill_switch_active,
    }


@app.post("/webhook")
def webhook(signal: Signal) -> dict:
    # The placeholder is public in the repo, so accepting it would let anyone trade.
    if _is_placeholder(config.TRADINGVIEW_WEBHOOK_SECRET):
        raise HTTPException(status_code=503, detail="TRADINGVIEW_WEBHOOK_SECRET not configured")
    if not _secret_matches(signal.secret, config.TRADINGVIEW_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")

    allowed, reason = risk.can_execute_trade(signal.side, signal.entry, signal.stop)
    if not allowed:
        reporter.send(f"Signal rejected: {reason} ({signal.side} {signal.symbol})")
        return {"status": "rejected", "reason": reason}

    size = risk.position_size(signal.entry, signal.stop)
    order = executor.market_order(signal.symbol, signal.side, size)
    reporter.send(f"{signal.side.upper()} {size:.4f} {signal.symbol} @ ~{signal.entry} (stop {signal.stop})")
    return {"status": "submitted", "order": order}


# --- Telegram dashboard ------------------------------------------------------------

def show_pnl() -> None:
    reporter.send(tg.format_pnl(risk.daily_stats()["pnl"], risk.account_balance),
                  reply_markup=tg.dashboard_keyboard(), html_format=True)


def show_positions() -> None:
    try:
        text = tg.format_positions(executor.get_open_positions(), dry_run=executor.dry_run)
    except Exception as exc:
        log.error("Fetching positions failed: %s", exc)
        text = f"❌ שגיאה בשליפת פוזיציות | Failed to fetch positions:\n<code>{html.escape(str(exc))}</code>"
    reporter.send(text, reply_markup=tg.dashboard_keyboard(), html_format=True)


def show_risk() -> None:
    pnl = risk.daily_stats()["pnl"]
    reporter.send(
        tg.format_risk(pnl, risk.max_daily_loss, risk.max_daily_loss_pct, risk.kill_switch_active),
        reply_markup=tg.dashboard_keyboard(), html_format=True,
    )


def request_kill_switch() -> None:
    reporter.send(
        "🚨 <b>KILL-SWITCH חירום | EMERGENCY</b>\n"
        "פעולה זו תסגור את <b>כל</b> הפוזיציות ותחסום מסחר עד 00:00 UTC.\n"
        "This closes <b>ALL</b> positions and blocks trading until 00:00 UTC.\n\n"
        "לאשר? | Confirm?",
        reply_markup=tg.kill_confirm_keyboard(), html_format=True,
    )


def confirm_kill_switch() -> None:
    try:
        results = risk.trigger_emergency_kill_switch("Telegram dashboard button")
    except Exception as exc:
        # The switch is already persisted as active; only the close failed.
        reporter.send(
            "❌ <b>סגירת חירום נכשלה | EMERGENCY CLOSE FAILED</b>\n"
            "⛔ המסחר חסום, אך יש לסגור פוזיציות ידנית! | Trading is blocked, close positions manually!\n"
            f"<code>{html.escape(str(exc))}</code>",
            reply_markup=tg.dashboard_keyboard(), html_format=True,
        )
        return
    reporter.send(tg.format_kill_confirmation(results), reply_markup=tg.dashboard_keyboard(), html_format=True)


def cancel_kill_switch() -> None:
    reporter.send_dashboard("✅ בוטל - לא בוצעה פעולה | Cancelled - no action taken")


BUTTON_HANDLERS = {
    tg.CB_PNL: show_pnl,
    tg.CB_POSITIONS: show_positions,
    tg.CB_RISK: show_risk,
    tg.CB_KILL_SWITCH: request_kill_switch,
    tg.CB_KILL_CONFIRM: confirm_kill_switch,
    tg.CB_KILL_CANCEL: cancel_kill_switch,
}


def _authorized(chat: dict) -> bool:
    return str(chat.get("id")) == str(config.TELEGRAM_CHAT_ID)


def handle_telegram_update(update: dict) -> dict:
    """Dispatch a Telegram update: a dashboard button press or a text command."""
    callback = update.get("callback_query")
    if callback:
        chat = (callback.get("message") or {}).get("chat") or {}
        if not _authorized(chat):
            log.warning("Ignoring button press from unauthorized chat %s", chat.get("id"))
            reporter.answer_callback(callback["id"], "⛔ Unauthorized")
            return {"ok": True}
        handler = BUTTON_HANDLERS.get(callback.get("data"))
        if handler is None:
            reporter.answer_callback(callback["id"], "❓ Unknown action")
            return {"ok": True}
        reporter.answer_callback(callback["id"])
        handler()
        return {"ok": True}

    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return {"ok": True}
    if not _authorized(message.get("chat") or {}):
        log.warning("Ignoring command from unauthorized chat %s", (message.get("chat") or {}).get("id"))
        return {"ok": True}
    command = text.split()[0].split("@")[0].lower()
    if command in ("/start", "/menu", "/dashboard"):
        reporter.send_dashboard()
    elif command == "/summary":
        stats = risk.daily_stats()
        reporter.send_daily_summary(stats["pnl"], stats["total_trades"], stats["win_rate"],
                                    stats["current_drawdown"], date=stats["date"])
    return {"ok": True}


@app.post("/telegram/webhook")
def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    if _is_placeholder(config.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=503, detail="TELEGRAM_WEBHOOK_SECRET not configured")
    if not _secret_matches(x_telegram_bot_api_secret_token, config.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")
    try:
        return handle_telegram_update(update)
    except Exception:
        # Still answer 200: Telegram re-delivers failed updates, which would repeat the action.
        log.exception("Telegram update failed")
        return {"ok": False}


def main() -> None:
    log.info(
        "Starting bot: environment=%s, balance=%s, daily loss limit=%.2f%%",
        config.ENVIRONMENT, config.ACCOUNT_BALANCE, config.MAX_DAILY_LOSS_PCT,
    )
    uvicorn.run(app, host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT)


if __name__ == "__main__":
    main()
