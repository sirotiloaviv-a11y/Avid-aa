from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading_bot.config import AccountConfig, DailyLossBasis, DrawdownMode, NewsConfig, RiskLimits, SessionConfig
from trading_bot.risk_manager import (
    CalendarUnavailable,
    EconomicEvent,
    HaltEvent,
    HttpCalendarProvider,
    Impact,
    NewsGuard,
    RiskEngine,
    get_instrument,
)
from trading_bot.utils import StateStore, StateStoreError

# Tuesday 2026-03-10 10:00 New York (DST) == 14:00 UTC; trading day 2026-03-10.
T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


class StaticProvider:
    def __init__(self, events: list[EconomicEvent] | None = None, fail: bool = False) -> None:
        self.events = events or []
        self.fail = fail
        self.calls = 0

    def fetch(self) -> list[EconomicEvent]:
        self.calls += 1
        if self.fail:
            raise CalendarUnavailable("down")
        return list(self.events)


class EngineTestCase(unittest.TestCase):
    limits = RiskLimits(
        daily_loss_limit_pct=1.5,
        daily_loss_basis=DailyLossBasis.INITIAL,
        max_drawdown_pct=5.0,
        max_drawdown_mode=DrawdownMode.TRAILING_INTRADAY,
        risk_per_trade_pct=0.5,
        max_trades_per_day=3,
        equity_stale_seconds=60,
    )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.db"
        self.store = StateStore(self.db)
        self.clock = Clock(T0)
        self.account = AccountConfig("acc", 100_000.0)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def engine(self, **kwargs: Any) -> RiskEngine:
        kwargs.setdefault("clock", self.clock)
        limits = kwargs.pop("limits", self.limits)
        return RiskEngine(self.account, limits, SessionConfig(), self.store, **kwargs)


class DailyLossTests(EngineTestCase):
    def test_allows_trading_within_limits(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        self.assertTrue(engine.check_new_trade().allowed)

    def test_halts_at_daily_limit_and_fires_callback(self) -> None:
        engine = self.engine()
        events: list[HaltEvent] = []
        engine.on_halt(events.append)
        engine.update_account(100_000, 100_000)
        engine.update_account(100_000, 98_600)  # -1.4%: still fine
        self.assertTrue(engine.check_new_trade().allowed)
        status = engine.update_account(100_000, 98_500)  # -1.5%: floor
        self.assertTrue(status.halted)
        self.assertTrue(status.should_flatten)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "daily_loss")
        decision = engine.check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertIn("daily loss limit", decision.reasons[0])
        # Equity recovering the same day does not lift the halt, nor re-fire it.
        engine.update_account(100_000, 99_900)
        self.assertFalse(engine.check_new_trade().allowed)
        self.assertEqual(len(events), 1)
        self.assertEqual(status.halted_until, datetime(2026, 3, 10, 21, 0, tzinfo=timezone.utc))

    def test_halt_survives_restart(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        engine.record_trade_opened("t1", "NQ", 400)
        engine.update_account(100_000, 98_400)
        self.clock.advance(minutes=1)

        restarted = self.engine()
        restarted.update_account(100_000, 99_000)
        status = restarted.status()
        self.assertTrue(status.halted)
        self.assertEqual(status.trades_today, 1)
        self.assertEqual(status.open_risk, 400)
        self.assertFalse(restarted.check_new_trade().allowed)

    def test_reset_clears_daily_halt_but_keeps_new_reference(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        engine.update_account(98_400, 98_400)
        self.assertFalse(engine.check_new_trade().allowed)
        # 17:00 New York = 21:00 UTC in March after DST.
        self.clock.now = datetime(2026, 3, 10, 21, 0, 1, tzinfo=timezone.utc)
        status = engine.update_account(98_400, 98_400)
        self.assertEqual(str(status.trading_day), "2026-03-11")
        self.assertFalse(status.halted)
        self.assertEqual(status.daily_loss_floor, 98_400 - 1_500)
        self.assertTrue(engine.check_new_trade().allowed)

    def test_day_start_reference_is_max_of_balance_and_equity(self) -> None:
        engine = self.engine()
        # Starts the day with $1,000 unrealized profit.
        status = engine.update_account(100_000, 101_000)
        self.assertEqual(status.day_start_reference, 101_000)
        self.assertEqual(status.daily_loss_floor, 99_500)

    def test_day_start_basis(self) -> None:
        limits = replace(self.limits, daily_loss_basis=DailyLossBasis.DAY_START)
        engine = self.engine(limits=limits)
        self.assertEqual(engine.update_account(120_000, 120_000).daily_loss_floor, 118_200)

    def test_new_day_without_snapshot_denies(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        self.clock.now = datetime(2026, 3, 10, 21, 0, 30, tzinfo=timezone.utc)
        decision = engine.check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertTrue(any("new trading day" in r for r in decision.reasons))


class DrawdownTests(EngineTestCase):
    def test_trailing_intraday_follows_peak_equity(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        self.assertEqual(engine.status().drawdown_floor, 95_000)
        engine.update_account(100_000, 102_000)  # unrealized peak
        # Floor would be 97,000 but locks at the initial balance.
        self.assertEqual(engine.status().drawdown_floor, 97_000)
        engine.update_account(100_000, 108_000)
        self.assertEqual(engine.status().drawdown_floor, 100_000)

    def test_trailing_without_lock(self) -> None:
        limits = replace(self.limits, drawdown_lock_at_initial=False)
        engine = self.engine(limits=limits)
        engine.update_account(100_000, 108_000)
        self.assertEqual(engine.status().drawdown_floor, 103_000)

    def test_breach_is_permanent_until_operator_clears(self) -> None:
        # Daily limit wider than DD, to exercise the DD floor on its own.
        limits = replace(self.limits, daily_loss_limit_pct=5.0, max_drawdown_pct=5.0)
        engine = self.engine(limits=limits)
        engine.update_account(100_000, 104_000)
        engine.update_account(100_000, 98_900)  # floor is 99,000
        self.assertTrue(engine.status().halted)
        self.clock.now = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        status = engine.update_account(98_900, 98_900)
        self.assertTrue(status.halted)
        self.assertIsNone(status.halted_until)
        with self.assertRaises(ValueError):
            engine.clear_max_drawdown_breach("wrong")
        engine.clear_max_drawdown_breach("acc")
        self.assertTrue(engine.check_new_trade().allowed)

    def test_trailing_eod_uses_closing_balance(self) -> None:
        limits = replace(self.limits, max_drawdown_mode=DrawdownMode.TRAILING_EOD)
        engine = self.engine(limits=limits)
        engine.update_account(100_000, 103_000)  # intraday peak ignored
        self.assertEqual(engine.status().drawdown_floor, 95_000)
        engine.update_account(101_000, 101_000)
        self.clock.now = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
        engine.update_account(101_000, 101_000)
        self.assertEqual(engine.status().drawdown_floor, 96_000)

    def test_static_drawdown(self) -> None:
        limits = replace(self.limits, max_drawdown_mode=DrawdownMode.STATIC)
        engine = self.engine(limits=limits)
        engine.update_account(100_000, 110_000)
        self.assertEqual(engine.status().drawdown_floor, 95_000)


class GateTests(EngineTestCase):
    def test_no_snapshot_denies(self) -> None:
        decision = self.engine().check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertIn("no account snapshot", decision.reasons[0])

    def test_stale_snapshot_denies(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        self.clock.advance(seconds=61)
        self.assertFalse(engine.check_new_trade().allowed)

    def test_max_trades_per_day(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        for i in range(3):
            engine.record_trade_opened(f"t{i}", "MNQ", 10)
            engine.record_trade_closed(f"t{i}", 5)
        decision = engine.check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertIn("max trades", decision.reasons[0])
        self.assertEqual(engine.status().realized_pnl_today, 15)

    def test_kill_switch_file(self) -> None:
        kill = Path(self.tmp.name) / "KILL"
        engine = self.engine(kill_switch_path=kill)
        engine.update_account(100_000, 100_000)
        self.assertTrue(engine.check_new_trade().allowed)
        kill.touch()
        self.assertFalse(engine.check_new_trade().allowed)

    def test_manual_halt_and_resume(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        engine.halt("operator")
        self.assertFalse(engine.check_new_trade().allowed)
        engine.resume_manual_halt()
        self.assertTrue(engine.check_new_trade().allowed)

    def test_failed_save_blocks_trading(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)

        def broken(*_: Any) -> None:
            raise StateStoreError("disk full")

        original = self.store.save_account
        self.store.save_account = broken  # type: ignore[method-assign]
        engine.update_account(100_000, 100_000)
        self.assertIn("state could not be saved to disk", engine.check_new_trade().reasons)
        self.store.save_account = original  # type: ignore[method-assign]
        engine.update_account(100_000, 100_000)
        self.assertTrue(engine.check_new_trade().allowed)

    def test_internal_error_fails_closed(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)

        def boom(_: datetime) -> list[str]:
            raise RuntimeError("bug")

        engine._blocking_reasons = boom  # type: ignore[method-assign]
        decision = engine.check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertIn("risk engine error", decision.reasons[0])

    def test_rejects_non_finite_snapshot(self) -> None:
        with self.assertRaises(ValueError):
            self.engine().update_account(100_000, float("nan"))


class PlanTradeTests(EngineTestCase):
    def test_budget_is_risk_percent(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        plan = engine.plan_trade(get_instrument("NQ"), 20000, 19980)  # $404/contract, $500 budget
        self.assertTrue(plan.approved)
        assert plan.size is not None
        self.assertEqual(plan.size.quantity, 1)

    def test_budget_capped_by_room_to_daily_floor(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        engine.update_account(100_000, 98_800)  # 300 room to 98,500 floor
        self.assertAlmostEqual(engine.risk_budget(), 240.0)  # 80% of room
        plan = engine.plan_trade(get_instrument("NQ"), 20000, 19980)
        self.assertFalse(plan.approved)
        self.assertIn("minimum size", plan.decision.reasons[0])
        plan = engine.plan_trade(get_instrument("MNQ"), 20000, 19980)  # $41/contract
        assert plan.size is not None
        self.assertEqual(plan.size.quantity, 5)

    def test_open_risk_reduces_budget(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        engine.record_trade_opened("t1", "NQ", 1_300)
        self.assertAlmostEqual(engine.risk_budget(), 160.0)  # (1500 - 1300) * 0.8

    def test_invalid_trade_is_denied_not_raised(self) -> None:
        engine = self.engine()
        engine.update_account(100_000, 100_000)
        plan = engine.plan_trade(get_instrument("NQ"), 20000, 20000)
        self.assertFalse(plan.approved)
        self.assertIn("invalid trade", plan.decision.reasons[0])


class NewsGuardTests(EngineTestCase):
    cpi = EconomicEvent("CPI m/m", "USD", datetime(2026, 3, 10, 12, 30, tzinfo=timezone.utc), Impact.HIGH)

    def guard(self, provider: StaticProvider, **overrides: Any) -> NewsGuard:
        return NewsGuard(provider, replace(NewsConfig(), **overrides), clock=self.clock)

    def test_blocks_15_minutes_either_side(self) -> None:
        guard = self.guard(StaticProvider([self.cpi]))

        def at(hour: int, minute: int) -> datetime:
            return datetime(2026, 3, 10, hour, minute, tzinfo=timezone.utc)

        self.assertTrue(guard.check(at(12, 14)).allowed)
        self.assertFalse(guard.check(at(12, 15)).allowed)
        self.assertFalse(guard.check(at(12, 30)).allowed)
        self.assertFalse(guard.check(at(12, 45)).allowed)
        self.assertTrue(guard.check(at(12, 46)).allowed)
        self.assertIn("CPI", guard.check(at(12, 20)).reason or "")

    def test_filters_currency_and_impact(self) -> None:
        eur = EconomicEvent("ECB Rate", "EUR", self.cpi.time, Impact.HIGH)
        low = EconomicEvent("Crude Inventories", "USD", self.cpi.time, Impact.LOW)
        keyword = EconomicEvent("FOMC Minutes", "USD", self.cpi.time, Impact.MEDIUM)
        guard = self.guard(StaticProvider([eur, low]))
        self.assertTrue(guard.check(self.cpi.time).allowed)
        guard = self.guard(StaticProvider([keyword]))
        self.assertFalse(guard.check(self.cpi.time).allowed)

    def test_fails_closed_without_data(self) -> None:
        guard = self.guard(StaticProvider(fail=True))
        check = guard.check()
        self.assertFalse(check.allowed)
        self.assertIn("fail-closed", check.reason or "")
        self.assertTrue(self.guard(StaticProvider(fail=True), fail_closed=False).check().allowed)

    def test_stale_data_fails_closed_and_retries(self) -> None:
        provider = StaticProvider([])
        guard = self.guard(provider, max_data_age_hours=24, refresh_minutes=360)
        self.assertTrue(guard.check().allowed)
        provider.fail = True
        self.clock.advance(hours=25)
        self.assertFalse(guard.check().allowed)
        calls = provider.calls
        guard.check()
        self.assertEqual(provider.calls, calls)  # no retry storm
        self.clock.advance(minutes=6)
        provider.fail = False
        self.assertTrue(guard.check().allowed)

    def test_engine_denies_during_blackout(self) -> None:
        self.clock.now = datetime(2026, 3, 10, 12, 25, tzinfo=timezone.utc)
        engine = self.engine(news_guard=self.guard(StaticProvider([self.cpi])))
        engine.update_account(100_000, 100_000)
        decision = engine.check_new_trade()
        self.assertFalse(decision.allowed)
        self.assertIn("news blackout", decision.reasons[0])

    def test_http_provider_caches_and_falls_back(self) -> None:
        cache = Path(self.tmp.name) / "cache.json"
        payload = json.dumps([
            {"title": "Non-Farm Employment Change", "country": "USD",
             "date": "2026-03-06T08:30:00-05:00", "impact": "High"},
            {"title": "broken", "country": "USD", "date": "not a date", "impact": "High"},
        ]).encode()
        def online(_url: str, _timeout: float) -> bytes:
            return payload

        provider = HttpCalendarProvider("http://x", cache, opener=online)
        events = provider.fetch()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].time, datetime(2026, 3, 6, 13, 30, tzinfo=timezone.utc))
        self.assertTrue(cache.exists())

        def offline(_url: str, _timeout: float) -> bytes:
            raise OSError("no route")

        self.assertEqual(len(HttpCalendarProvider("http://x", cache, opener=offline).fetch()), 1)
        stale = HttpCalendarProvider("http://x", cache, opener=offline, max_cache_age=timedelta(0))
        with self.assertRaises(CalendarUnavailable):
            stale.fetch()


if __name__ == "__main__":
    unittest.main()
