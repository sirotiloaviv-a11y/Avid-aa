"""Maps engine statuses, the trade journal and the audit log to dashboard JSON.

Everything here is a pure function of its inputs, so the mapping (badges,
aggregates, percentages) is unit-tested without a server.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from ..risk_manager.news_guard import EconomicEvent, NewsCheck
from ..risk_manager.risk_engine import RiskStatus
from ..utils.state_store import RiskEventRecord, TradeRecord


class Badge:
    ACTIVE = "ACTIVE"
    HIGH_RISK = "HIGH_RISK"
    HALTED = "HALTED"
    PAUSED = "PAUSED"
    # No account snapshot yet, or the last one is older than the stale limit.
    OFFLINE = "OFFLINE"


class Overall:
    ACTIVE = "ACTIVE"
    PARTIAL = "PARTIAL"  # some accounts halted or paused
    HALTED = "HALTED"    # kill switch set, or no account may trade


EXIT_STATUS: dict[str, str] = {
    "tp": "TP",
    "sl": "SL",
    "news_halt": "NEWS",
    "daily_halt": "DAILY HALT",
    "manual": "MANUAL",
    "other": "CLOSED",
}


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def account_badge(status: RiskStatus, *, now: datetime, stale_after: timedelta, high_risk_pct: float) -> str:
    risk_halted = status.halted and any(not r.startswith("paused") for r in status.halt_reasons)
    if risk_halted:
        return Badge.HALTED
    if status.paused:
        return Badge.PAUSED
    if status.last_update is None or now - status.last_update > stale_after:
        return Badge.OFFLINE
    usage = [u for u in (status.daily_loss_used_pct, status.drawdown_used_pct) if u is not None]
    if usage and max(usage) >= high_risk_pct:
        return Badge.HIGH_RISK
    return Badge.ACTIVE


def account_view(
    index: int, status: RiskStatus, *, now: datetime, stale_after: timedelta, high_risk_pct: float
) -> dict[str, Any]:
    reference = status.day_start_reference
    day_pnl_pct = (status.daily_pnl / reference * 100
                   if status.daily_pnl is not None and reference else None)
    return {
        "index": index,
        "name": f"Account #{index}",
        "id": status.account_id,
        "badge": account_badge(status, now=now, stale_after=stale_after, high_risk_pct=high_risk_pct),
        "balance": _round(status.balance),
        "equity": _round(status.equity),
        "initial_balance": _round(status.initial_balance),
        "day_pnl": _round(status.daily_pnl),
        "day_pnl_pct": _round(day_pnl_pct, 3),
        "daily": {
            "used_pct": _round(status.daily_loss_used_pct, 1),
            "limit": _round(status.daily_loss_limit),
            "room": _round(status.daily_room),
            "floor": _round(status.daily_loss_floor),
        },
        "drawdown": {
            "used_pct": _round(status.drawdown_used_pct, 1),
            "allowance": _round(status.drawdown_allowance),
            "room": _round(status.drawdown_room),
            "floor": _round(status.drawdown_floor),
            "high_water_mark": _round(status.high_water_mark),
        },
        "trades_today": status.trades_today,
        "win_rate": _round(status.wins_today / status.closed_today * 100, 1) if status.closed_today else None,
        "open_trades": len(status.open_trades),
        "open_risk": _round(status.open_risk),
        "paused": status.paused,
        "manual_halt": status.manual_halt,
        "halt_reasons": list(status.halt_reasons),
        "halted_until": _iso(status.halted_until),
        "last_update": _iso(status.last_update),
    }


def overall_view(statuses: Sequence[RiskStatus], *, kill_switch: bool) -> dict[str, Any]:
    equities = [s.equity for s in statuses if s.equity is not None]
    balances = [s.balance for s in statuses if s.balance is not None]
    pnls = [s.daily_pnl for s in statuses if s.daily_pnl is not None]
    references = [s.day_start_reference for s in statuses
                  if s.daily_pnl is not None and s.day_start_reference]
    halted = sum(1 for s in statuses if s.halted)
    if kill_switch or (statuses and halted == len(statuses)):
        state = Overall.HALTED
    elif halted:
        state = Overall.PARTIAL
    else:
        state = Overall.ACTIVE
    day_pnl = sum(pnls) if pnls else None
    return {
        "status": state,
        "kill_switch": kill_switch,
        "accounts": len(statuses),
        "accounts_halted": halted,
        "total_equity": _round(sum(equities)) if equities else None,
        "total_balance": _round(sum(balances)) if balances else None,
        "day_pnl": _round(day_pnl),
        "day_pnl_pct": _round(day_pnl / sum(references) * 100, 3)
        if day_pnl is not None and references else None,
    }


def trade_view(trade: TradeRecord) -> dict[str, Any]:
    status = "OPEN" if trade.is_open else EXIT_STATUS.get(trade.exit_reason or "other", "CLOSED")
    return {
        "time": _iso(trade.closed_at or trade.opened_at),
        "opened_at": _iso(trade.opened_at),
        "closed_at": _iso(trade.closed_at),
        "account": trade.account_id,
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "side": trade.direction.upper() if trade.direction else None,
        "entry": trade.entry_price,
        "exit": trade.exit_price,
        "stop": trade.stop_price,
        "size": trade.quantity,
        "pnl": _round(trade.realized_pnl),
        "status": status,
    }


def event_view(event: RiskEventRecord) -> dict[str, Any]:
    return {"time": _iso(event.ts), "account": event.account_id, "kind": event.kind, "message": event.message}


def news_view(
    upcoming: Sequence[EconomicEvent], check: NewsCheck | None, *, enabled: bool
) -> dict[str, Any]:
    nxt = upcoming[0] if upcoming else None
    return {
        "enabled": enabled,
        "blocked": check is not None and not check.allowed,
        "reason": check.reason if check is not None else None,
        "next": None if nxt is None else {
            "title": nxt.title, "currency": nxt.currency, "time": _iso(nxt.time),
        },
        "upcoming": [{"title": e.title, "currency": e.currency, "time": _iso(e.time)} for e in upcoming[:10]],
    }


def build_snapshot(
    statuses: Sequence[RiskStatus],
    trades: Sequence[TradeRecord],
    events: Sequence[RiskEventRecord],
    *,
    kill_switch: bool,
    news: dict[str, Any],
    environment: str,
    now: datetime,
    stale_after: timedelta,
    high_risk_pct: float,
) -> dict[str, Any]:
    return {
        "server_time": _iso(now),
        "environment": environment,
        "overall": overall_view(statuses, kill_switch=kill_switch),
        "news": news,
        "accounts": [
            account_view(i, s, now=now, stale_after=stale_after, high_risk_pct=high_risk_pct)
            for i, s in enumerate(statuses, start=1)
        ],
        "trades": [trade_view(t) for t in trades],
        "activity": [event_view(e) for e in events],
    }
