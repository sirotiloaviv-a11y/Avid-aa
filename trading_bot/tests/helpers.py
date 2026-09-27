"""Shared fixtures for the trading bot tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from trading_bot.risk_manager import RiskStatus

AT = datetime(2026, 3, 10, 14, 30, tzinfo=timezone.utc)


def make_status(account_id: str = "apex_nq_1", **overrides: object) -> RiskStatus:
    values: dict[str, object] = dict(
        account_id=account_id, initial_balance=50_000.0, trading_day=date(2026, 3, 10),
        balance=50_000.0, equity=49_700.0, last_update=AT, day_start_reference=50_000.0,
        daily_pnl=-300.0, daily_loss_floor=49_250.0, daily_room=450.0, drawdown_floor=47_500.0,
        drawdown_room=2_200.0, drawdown_used_pct=12.0, daily_loss_limit=750.0,
        drawdown_allowance=2_500.0, high_water_mark=50_000.0, open_risk=0.0, trades_today=2,
        realized_pnl_today=-300.0, wins_today=1, losses_today=1, closed_today=2,
        daily_loss_used_pct=40.0, open_trades=(), halted=False, halt_reasons=(),
        should_flatten=False, halted_until=None,
    )
    values.update(overrides)
    return RiskStatus(**values)  # type: ignore[arg-type]
