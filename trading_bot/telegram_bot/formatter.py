"""Pure functions that turn risk events and statuses into Telegram HTML.

Telegram's HTML mode is used rather than MarkdownV2: it needs only ``<``,
``>`` and ``&`` escaped, where MarkdownV2 reserves 18 characters and rejects
the whole message if one slips through, which is the wrong failure mode for
an alert. Every dynamic value goes through :func:`esc`.

Each line's tags open and close on that line, so :func:`split_message` can
cut on line boundaries without breaking markup.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from typing import Sequence

from ..risk_manager.events import (
    Direction,
    DrawdownWarningEvent,
    ExitReason,
    HaltEvent,
    HaltKind,
    TradeClosedEvent,
    TradeOpenedEvent,
)
from ..risk_manager.news_guard import EconomicEvent, NewsCheck
from ..risk_manager.risk_engine import RiskStatus
from .api import MAX_MESSAGE_LENGTH

DASH = "—"

EXIT_REASON_LABELS: dict[ExitReason, str] = {
    ExitReason.TAKE_PROFIT: "Take profit",
    ExitReason.STOP_LOSS: "Stop loss",
    ExitReason.NEWS_HALT: "News halt",
    ExitReason.DAILY_HALT: "Daily halt",
    ExitReason.MANUAL: "Manual",
    ExitReason.SIGNAL: "Strategy exit",
    ExitReason.RISK_HALT: "Risk halt",
    ExitReason.OTHER: "Other",
}

HALT_LABELS: dict[str, str] = {
    HaltKind.DAILY_LOSS: "DAILY LOSS LIMIT",
    HaltKind.MAX_DRAWDOWN: "MAX DRAWDOWN BREACHED",
    HaltKind.MANUAL: "MANUAL HALT",
}


# ------------------------------------------------------------------ values
def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def fmt_money(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return DASH
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}${abs(value):,.2f}"


def fmt_pct(value: float | None, *, signed: bool = False, digits: int = 2) -> str:
    if value is None:
        return DASH
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def fmt_price(value: float | None) -> str:
    if value is None:
        return DASH
    magnitude = abs(value)
    digits = 2 if magnitude >= 100 else 4 if magnitude >= 1 else 6
    return f"{value:,.{digits}f}"


def fmt_qty(value: float | None) -> str:
    if value is None:
        return DASH
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def fmt_time(ts: datetime | None) -> str:
    return DASH if ts is None else f"{ts:%Y-%m-%d %H:%M} UTC"


def progress_bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "▓" * filled + "░" * (width - filled)


# ------------------------------------------------------------------ events
def format_trade_entry(event: TradeOpenedEvent) -> str:
    direction = event.direction.value.upper() if event.direction else "ENTRY"
    icon = {Direction.LONG: "🟢", Direction.SHORT: "🔴", None: "🔵"}[event.direction]
    lines = [
        f"{icon} <b>{esc(direction)} {esc(event.symbol)}</b>",
        f"Account: <code>{esc(event.account_id)}</code>",
        f"Entry: <b>{fmt_price(event.entry_price)}</b>",
    ]
    stop_line = f"Stop loss: {fmt_price(event.stop_price)}"
    if event.entry_price is not None and event.stop_price is not None:
        stop_line += f" ({abs(event.entry_price - event.stop_price):,.2f} pts)"
    lines.append(stop_line)
    tp_line = f"Take profit: {fmt_price(event.take_profit)}"
    entry, stop, target = event.entry_price, event.stop_price, event.take_profit
    if entry is not None and stop is not None and target is not None and entry != stop:
        tp_line += f" (R:R {abs(target - entry) / abs(entry - stop):.2f})"
    lines.append(tp_line)
    lines.append(f"Size: {fmt_qty(event.quantity)}")
    lines.append(f"Risk: <b>{fmt_money(event.risk_amount)}</b> ({fmt_pct(event.risk_pct)})")
    lines.append(f"<i>{esc(fmt_time(event.at))} · #{esc(event.trade_id)}</i>")
    return "\n".join(lines)


def format_trade_exit(event: TradeClosedEvent) -> str:
    if event.realized_pnl > 0:
        icon = "✅"
    elif event.realized_pnl < 0:
        icon = "❌"
    else:
        icon = "➖"
    symbol = event.symbol or "unknown symbol"
    lines = [
        f"{icon} <b>EXIT {esc(symbol)}</b> · {esc(EXIT_REASON_LABELS[event.reason])}",
        f"Account: <code>{esc(event.account_id)}</code>",
    ]
    if event.entry_price is not None:
        lines.append(f"Entry: {fmt_price(event.entry_price)}")
    lines.extend([
        f"Exit: <b>{fmt_price(event.exit_price)}</b>",
        f"P&amp;L: <b>{fmt_money(event.realized_pnl, signed=True)}</b> "
        f"({fmt_pct(event.pnl_pct, signed=True)})",
        f"Balance: {fmt_money(event.balance)}",
        f"<i>{esc(fmt_time(event.at))} · #{esc(event.trade_id)}</i>",
    ])
    return "\n".join(lines)


def format_drawdown_warning(event: DrawdownWarningEvent) -> str:
    icon = "🚨" if event.level_pct >= 80 else "⚠️"
    return "\n".join([
        f"{icon} <b>DAILY DRAWDOWN {event.level_pct}%</b>",
        f"Account: <code>{esc(event.account_id)}</code>",
        f"{progress_bar(event.used_pct)} {fmt_pct(event.used_pct, digits=0)} of daily limit used",
        f"Day P&amp;L: <b>{fmt_money(event.daily_pnl, signed=True)}</b> "
        f"of {fmt_money(-event.daily_limit)} allowed",
        f"Equity: {fmt_money(event.equity)} · halt at {fmt_money(event.floor)}",
        f"Room left: <b>{fmt_money(event.equity - event.floor)}</b>",
    ])


def format_halt(event: HaltEvent, halted_until: datetime | None = None) -> str:
    label = HALT_LABELS.get(event.kind, event.kind.upper())
    lines = [
        f"🛑 <b>TRADING HALTED · {esc(label)}</b>",
        f"Account: <code>{esc(event.account_id)}</code>",
        f"{esc(event.reason)}",
    ]
    if event.should_flatten:
        lines.append("Open positions are being flattened. No new entries.")
    if halted_until is not None:
        lines.append(f"Resumes after the daily reset: {esc(fmt_time(halted_until))}")
    elif event.kind in (HaltKind.MAX_DRAWDOWN, HaltKind.MANUAL):
        lines.append("Stays halted until an operator clears it.")
    return "\n".join(lines)


# ---------------------------------------------------------------- replies
def _status_block(status: RiskStatus) -> list[str]:
    if status.halted and all(r.startswith("paused") for r in status.halt_reasons):
        state = "⏸ PAUSED"
    else:
        state = "🛑 HALTED" if status.halted else "🟢 OK"
    lines = [
        f"<b>{esc(status.account_id)}</b> · {state}",
        f"Balance {fmt_money(status.balance)} · Equity {fmt_money(status.equity)}",
        f"Day P&amp;L {fmt_money(status.daily_pnl, signed=True)} · "
        f"realized {fmt_money(status.realized_pnl_today, signed=True)}",
    ]
    if status.daily_loss_used_pct is not None:
        lines.append(
            f"Daily DD {progress_bar(status.daily_loss_used_pct)} "
            f"{fmt_pct(status.daily_loss_used_pct, digits=0)} · room {fmt_money(status.daily_room)}"
        )
    lines.append(
        f"Max DD floor {fmt_money(status.drawdown_floor)} · room {fmt_money(status.drawdown_room)}"
    )
    lines.append(f"Trades today {status.trades_today} · open {len(status.open_trades)}"
                 f" · open risk {fmt_money(status.open_risk)}")
    for trade in status.open_trades:
        side = (trade.direction or "").upper() or "OPEN"
        lines.append(
            f"  • {esc(side)} {esc(trade.symbol)} {fmt_qty(trade.quantity)} @ "
            f"{fmt_price(trade.entry_price)} · SL {fmt_price(trade.stop_price)} · "
            f"risk {fmt_money(trade.risk)}"
        )
    for reason in status.halt_reasons:
        lines.append(f"  ! {esc(reason)}")
    if status.last_update is None:
        lines.append("  ! no account snapshot yet")
    return lines


def format_status(
    statuses: Sequence[RiskStatus], *, kill_switch_active: bool, now: datetime
) -> str:
    lines = [f"📊 <b>Status</b> · {esc(fmt_time(now))}"]
    if kill_switch_active:
        lines.append("🛑 <b>KILL SWITCH ACTIVE</b>: no new entries on any account")
    for status in statuses:
        lines.append("")
        lines.extend(_status_block(status))
    if not statuses:
        lines.append("No accounts configured.")
    return "\n".join(lines)


def format_news(
    events: Sequence[EconomicEvent], check: NewsCheck, *, enabled: bool, now: datetime
) -> str:
    if not enabled:
        return "📰 News safeguard is disabled (NEWS_CALENDAR_SOURCE=none)."
    lines = [f"📰 <b>High-impact news</b> · next 24h from {esc(fmt_time(now))}"]
    lines.append("🟢 Entries allowed" if check.allowed else f"⛔ {esc(check.reason or 'blocked')}")
    lines.append("")
    if not events:
        lines.append("No high-impact events scheduled.")
    for event in events:
        lines.append(f"<b>{event.time:%H:%M}</b> UTC · {esc(event.currency)} · {esc(event.title)}")
    return "\n".join(lines)


def format_daily_summary(statuses: Sequence[RiskStatus], trading_day: date | None) -> str:
    total_trades = sum(s.trades_today for s in statuses)
    wins = sum(s.wins_today for s in statuses)
    closed = sum(s.closed_today for s in statuses)
    realized = sum(s.realized_pnl_today for s in statuses)
    day_pnl = sum(s.daily_pnl or 0.0 for s in statuses)
    win_rate = wins / closed * 100 if closed else None
    day = trading_day.isoformat() if trading_day else DASH

    lines = [
        f"🗓 <b>Daily summary · {esc(day)}</b>",
        f"Trades: <b>{total_trades}</b> · closed {closed} · win rate {fmt_pct(win_rate, digits=0)}",
        f"Realized P&amp;L: <b>{fmt_money(realized, signed=True)}</b>",
        f"Day P&amp;L (equity): <b>{fmt_money(day_pnl, signed=True)}</b>",
        "",
    ]
    for s in statuses:
        rate = fmt_pct(s.wins_today / s.closed_today * 100, digits=0) if s.closed_today else DASH
        flag = " 🛑" if s.halted else ""
        lines.append(
            f"<code>{esc(s.account_id)}</code>{flag}: {s.trades_today} trades · win {rate} · "
            f"{fmt_money(s.daily_pnl, signed=True)} · bal {fmt_money(s.balance)}"
        )
    return "\n".join(lines)


HELP_TEXT = "\n".join([
    "🤖 <b>Trading bot commands</b>",
    "/status: P&amp;L, open trades and drawdown for every account",
    "/news: today's high-impact events and blackout state",
    "/halt [reason]: emergency halt on ALL accounts (creates state/KILL)",
    "/resume: clear the manual halt (daily and max-DD halts stay)",
    "/help: this message",
])


# ---------------------------------------------------------------- helpers
def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split on line boundaries into chunks Telegram will accept."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single overlong line: hard cut
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]
