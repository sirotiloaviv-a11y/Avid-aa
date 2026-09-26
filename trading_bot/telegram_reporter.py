"""Telegram reporting and the interactive dashboard.

Messages use Telegram's HTML parse mode. Anything dynamic (symbols, error
text) goes through html.escape so it can't break the markup.
"""

import html
import logging
from datetime import datetime, timezone

import requests

import config

log = logging.getLogger(__name__)

# callback_data values sent back by the dashboard buttons.
CB_PNL = "PNL"
CB_POSITIONS = "POSITIONS"
CB_RISK = "RISK"
CB_KILL_SWITCH = "KILL_SWITCH"
CB_KILL_CONFIRM = "KILL_CONFIRM"
CB_KILL_CANCEL = "KILL_CANCEL"

DIVIDER = "━━━━━━━━━━━━━━"


def dashboard_keyboard() -> dict:
    """The 2x2 dashboard inline keyboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "📊 PNL יומי", "callback_data": CB_PNL},
                {"text": "🔓 פוזיציות פתוחות", "callback_data": CB_POSITIONS},
            ],
            [
                {"text": "🛡️ סטטוס סיכון", "callback_data": CB_RISK},
                {"text": "🚨 KILL-SWITCH חירום", "callback_data": CB_KILL_SWITCH},
            ],
        ]
    }


def kill_confirm_keyboard() -> dict:
    """Second step for the kill switch, so a stray tap can't flatten the account."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ אישור - סגור הכל | Confirm", "callback_data": CB_KILL_CONFIRM},
                {"text": "❌ ביטול | Cancel", "callback_data": CB_KILL_CANCEL},
            ]
        ]
    }


# --- formatting helpers ------------------------------------------------------

def fmt_usd(value: float, signed: bool = False) -> str:
    sign = ("+" if value > 0 else "-" if value < 0 else "") if signed else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def fmt_pct(value: float, signed: bool = False) -> str:
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _pnl_icon(value: float) -> str:
    return "🟢" if value > 0 else "🔴" if value < 0 else "⚪"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --- message builders ----------------------------------------------------------

def format_daily_summary(
    pnl: float,
    total_trades: int,
    win_rate: float,
    current_drawdown: float,
    account_balance: float = config.ACCOUNT_BALANCE,
    date: str = None,
) -> str:
    """win_rate is a percentage (0-100); current_drawdown is in dollars."""
    date = date or datetime.now(timezone.utc).date().isoformat()
    return "\n".join([
        f"📋 <b>סיכום יומי | Daily Summary</b>",
        f"🗓 {html.escape(date)}",
        DIVIDER,
        f"{_pnl_icon(pnl)} P&amp;L: <b>{fmt_usd(pnl, signed=True)}</b> ({fmt_pct(100 * pnl / account_balance, signed=True)})",
        f"🔢 עסקאות | Trades: <b>{total_trades}</b>",
        f"🎯 אחוז הצלחה | Win rate: <b>{fmt_pct(win_rate)}</b>",
        f"📉 דרודאון | Drawdown: <b>{fmt_usd(current_drawdown)}</b> ({fmt_pct(100 * current_drawdown / account_balance)})",
    ])


def format_pnl(daily_pnl: float, account_balance: float) -> str:
    equity = account_balance + daily_pnl
    return "\n".join([
        "📊 <b>PNL יומי | Daily P&amp;L</b>",
        DIVIDER,
        f"{_pnl_icon(daily_pnl)} היום | Today: <b>{fmt_usd(daily_pnl, signed=True)}</b> ({fmt_pct(100 * daily_pnl / account_balance, signed=True)})",
        f"🏦 יתרת בסיס | Base balance: {fmt_usd(account_balance)}",
        f"💼 הון נוכחי | Equity: <b>{fmt_usd(equity)}</b>",
        f"🕒 {_utc_now()}",
    ])


def format_positions(positions: list[dict], dry_run: bool = False) -> str:
    header = "🔓 <b>פוזיציות פתוחות | Open Positions</b>" + (" <i>(DRY RUN)</i>" if dry_run else "")
    if not positions:
        return "\n".join([header, DIVIDER, "✅ אין פוזיציות פתוחות | No open positions"])

    lines = [header, DIVIDER]
    for pos in positions:
        side = pos.get("side", "?")
        arrow = "🟩 LONG" if side == "long" else "🟥 SHORT" if side == "short" else html.escape(str(side))
        line = f"{arrow} <b>{html.escape(str(pos.get('symbol')))}</b> × {float(pos.get('contracts') or 0):,.4f}"
        entry = pos.get("entryPrice")
        if entry:
            line += f" @ {float(entry):,.2f}"
        upnl = pos.get("unrealizedPnl")
        if upnl is not None:
            line += f"  |  uPnL {_pnl_icon(float(upnl))} {fmt_usd(float(upnl), signed=True)}"
        lines.append(line)
    lines.append(f"סה״כ | Total: <b>{len(positions)}</b>")
    return "\n".join(lines)


def format_risk(daily_pnl: float, max_daily_loss: float, max_daily_loss_pct: float, kill_switch_active: bool) -> str:
    loss = max(0.0, -daily_pnl)
    used_pct = 100 * loss / max_daily_loss if max_daily_loss else 0.0
    filled = min(10, round(used_pct / 10))
    bar = "🟥" * filled + "⬜" * (10 - filled)
    if kill_switch_active:
        status = "🔴 <b>פעיל - המסחר חסום | ACTIVE - trading blocked</b>"
    elif used_pct >= 80:
        status = "🟠 כבוי - קרוב למגבלה | OFF - near limit"
    else:
        status = "🟢 כבוי - מסחר פעיל | OFF - trading enabled"
    return "\n".join([
        "🛡️ <b>סטטוס סיכון | Risk Status</b>",
        DIVIDER,
        f"📉 הפסד יומי | Daily loss: <b>{fmt_usd(loss)}</b> / {fmt_usd(max_daily_loss)} ({fmt_pct(max_daily_loss_pct)})",
        f"{bar} {used_pct:.0f}%",
        f"💵 נותר | Remaining: <b>{fmt_usd(max(0.0, max_daily_loss - loss))}</b>",
        f"🚨 Kill-Switch: {status}",
    ])


def format_kill_confirmation(results: list[dict]) -> str:
    closed = [r for r in results if r.get("status") == "closed"]
    failed = [r for r in results if r.get("status") == "error"]
    lines = [
        "🚨 <b>KILL-SWITCH הופעל | ACTIVATED</b>",
        DIVIDER,
        "⛔ המסחר חסום עד 00:00 UTC | Trading blocked until 00:00 UTC",
        f"✅ נסגרו | Closed: <b>{len(closed)}</b>",
    ]
    lines += [f"   • {html.escape(str(r['symbol']))}" for r in closed]
    if failed:
        lines.append(f"❌ נכשלו | Failed: <b>{len(failed)}</b> — סגור ידנית! Close manually!")
        lines += [f"   • {html.escape(str(r['symbol']))}: {html.escape(str(r.get('error')))}" for r in failed]
    if not results:
        lines.append("ℹ️ לא היו פוזיציות פתוחות | No open positions")
    lines.append(f"🕒 {_utc_now()}")
    return "\n".join(lines)


# --- Bot API client --------------------------------------------------------------

class TelegramReporter:
    def __init__(self, token: str = config.TELEGRAM_BOT_TOKEN, chat_id: str = config.TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return not (self.token.startswith("YOUR_") or self.chat_id.startswith("YOUR_"))

    def _call(self, method: str, payload: dict) -> bool:
        """POST to the Bot API. Returns False (and logs) instead of raising,
        so a Telegram outage never interrupts trading."""
        if not self.enabled:
            log.info("[telegram disabled] %s %s", method, payload.get("text", ""))
            return False
        try:
            resp = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Telegram %s failed: %s", method, exc)
            return False

    def send(self, text: str, reply_markup: dict = None, html_format: bool = False) -> bool:
        payload = {"chat_id": self.chat_id, "text": text}
        if html_format:
            payload["parse_mode"] = "HTML"
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def send_dashboard(self, text: str = None) -> bool:
        text = text or "🤖 <b>לוח בקרה | Dashboard</b>\nבחר פעולה | Choose an action:"
        return self.send(text, reply_markup=dashboard_keyboard(), html_format=True)

    def send_daily_summary(self, pnl: float, total_trades: int, win_rate: float, current_drawdown: float,
                           date: str = None) -> bool:
        return self.send(
            format_daily_summary(pnl, total_trades, win_rate, current_drawdown, date=date),
            reply_markup=dashboard_keyboard(),
            html_format=True,
        )

    def answer_callback(self, callback_query_id: str, text: str = None) -> bool:
        """Acknowledge a button press (stops the loading spinner in the client)."""
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

    def set_webhook(self, url: str, secret_token: str) -> bool:
        """Point Telegram at our /telegram/webhook; it will send secret_token
        back in the X-Telegram-Bot-Api-Secret-Token header."""
        return self._call("setWebhook", {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": ["message", "callback_query"],
        })
