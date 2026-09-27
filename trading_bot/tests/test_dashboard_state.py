from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from trading_bot.dashboard.state import (
    Badge,
    Overall,
    account_badge,
    account_view,
    build_snapshot,
    news_view,
    overall_view,
    trade_view,
)
from trading_bot.risk_manager import EconomicEvent, Impact, NewsCheck
from trading_bot.utils import RiskEventRecord, TradeRecord

from .helpers import AT, make_status

STALE = timedelta(seconds=120)


def badge(**overrides: object) -> str:
    return account_badge(make_status("acc", **overrides), now=AT, stale_after=STALE, high_risk_pct=80)


class BadgeTests(unittest.TestCase):
    def test_active(self) -> None:
        self.assertEqual(badge(), Badge.ACTIVE)

    def test_high_risk_from_daily_or_max_drawdown(self) -> None:
        self.assertEqual(badge(daily_loss_used_pct=80.0), Badge.HIGH_RISK)
        self.assertEqual(badge(drawdown_used_pct=85.0), Badge.HIGH_RISK)
        self.assertEqual(badge(daily_loss_used_pct=79.9), Badge.ACTIVE)

    def test_halted_beats_everything(self) -> None:
        self.assertEqual(badge(halted=True, halt_reasons=("daily loss limit hit",),
                               daily_loss_used_pct=100.0, paused=True), Badge.HALTED)

    def test_paused_only(self) -> None:
        self.assertEqual(badge(halted=True, halt_reasons=("paused: lunch",), paused=True), Badge.PAUSED)

    def test_offline_without_fresh_snapshot(self) -> None:
        self.assertEqual(badge(last_update=None), Badge.OFFLINE)
        self.assertEqual(badge(last_update=AT - timedelta(minutes=5)), Badge.OFFLINE)


class AccountViewTests(unittest.TestCase):
    def test_maps_fields(self) -> None:
        view = account_view(2, make_status(), now=AT, stale_after=STALE, high_risk_pct=80)
        self.assertEqual(view["name"], "Account #2")
        self.assertEqual(view["id"], "apex_nq_1")
        self.assertEqual(view["day_pnl"], -300.0)
        self.assertEqual(view["day_pnl_pct"], -0.6)
        self.assertEqual(view["daily"], {"used_pct": 40.0, "limit": 750.0, "room": 450.0, "floor": 49_250.0})
        self.assertEqual(view["drawdown"]["used_pct"], 12.0)
        self.assertEqual(view["win_rate"], 50.0)
        self.assertEqual(view["last_update"], AT.isoformat())

    def test_missing_snapshot_maps_to_none(self) -> None:
        view = account_view(1, make_status(equity=None, daily_pnl=None, day_start_reference=None,
                                           closed_today=0, wins_today=0),
                            now=AT, stale_after=STALE, high_risk_pct=80)
        self.assertIsNone(view["day_pnl_pct"])
        self.assertIsNone(view["win_rate"])


class OverallTests(unittest.TestCase):
    def test_totals(self) -> None:
        view = overall_view([make_status("a"), make_status("b", equity=50_600.0, daily_pnl=600.0)],
                            kill_switch=False)
        self.assertEqual(view["status"], Overall.ACTIVE)
        self.assertEqual(view["total_equity"], 100_300.0)
        self.assertEqual(view["day_pnl"], 300.0)
        self.assertEqual(view["day_pnl_pct"], 0.3)

    def test_partial_and_halted(self) -> None:
        ok, halted = make_status("a"), make_status("b", halted=True, halt_reasons=("x",))
        self.assertEqual(overall_view([ok, halted], kill_switch=False)["status"], Overall.PARTIAL)
        self.assertEqual(overall_view([halted], kill_switch=False)["status"], Overall.HALTED)
        self.assertEqual(overall_view([ok], kill_switch=True)["status"], Overall.HALTED)

    def test_accounts_without_data_are_left_out_of_totals(self) -> None:
        view = overall_view([make_status(equity=None, balance=None, daily_pnl=None)], kill_switch=False)
        self.assertIsNone(view["total_equity"])
        self.assertIsNone(view["day_pnl"])
        self.assertIsNone(view["day_pnl_pct"])


class TradeAndNewsTests(unittest.TestCase):
    def test_trade_view(self) -> None:
        closed = TradeRecord("a", "t1", "NQ", "long", 20000.0, 19980.0, 20040.0, 2.0, 808.0,
                             AT, 20040.0, 1600.0, "tp", AT + timedelta(minutes=5))
        view = trade_view(closed)
        self.assertEqual((view["side"], view["status"], view["pnl"]), ("LONG", "TP", 1600.0))
        self.assertEqual(view["time"], (AT + timedelta(minutes=5)).isoformat())
        opened = trade_view(TradeRecord("a", "t2", "BTCUSDT", "short", 60000.0, 60500.0, None, 0.4, 200.0, AT))
        self.assertEqual((opened["status"], opened["exit"], opened["time"]), ("OPEN", None, AT.isoformat()))
        for reason, label in (("sl", "SL"), ("news_halt", "NEWS"), ("daily_halt", "DAILY HALT"),
                              ("manual", "MANUAL"), ("other", "CLOSED")):
            record = TradeRecord("a", "x", "NQ", None, None, None, None, None, 0.0, AT, 1.0, 0.0, reason, AT)
            self.assertEqual(trade_view(record)["status"], label)

    def test_news_view(self) -> None:
        cpi = EconomicEvent("CPI m/m", "USD", AT + timedelta(hours=1), Impact.HIGH)
        view = news_view([cpi], NewsCheck(True), enabled=True)
        self.assertEqual(view["next"], {"title": "CPI m/m", "currency": "USD", "time": cpi.time.isoformat()})
        self.assertFalse(view["blocked"])
        blocked = news_view([], NewsCheck(False, "news blackout"), enabled=True)
        self.assertTrue(blocked["blocked"])
        self.assertIsNone(blocked["next"])

    def test_snapshot_shape(self) -> None:
        now = datetime(2026, 3, 10, 14, 31, tzinfo=timezone.utc)
        snap = build_snapshot(
            [make_status("a"), make_status("b")], [], [RiskEventRecord("a", AT, "halt:manual", "x")],
            kill_switch=False, news=news_view([], None, enabled=False), environment="paper",
            now=now, stale_after=STALE, high_risk_pct=80,
        )
        self.assertEqual(set(snap), {"server_time", "environment", "overall", "news", "accounts",
                                     "trades", "activity"})
        self.assertEqual([a["name"] for a in snap["accounts"]], ["Account #1", "Account #2"])
        self.assertEqual(snap["activity"][0]["kind"], "halt:manual")


if __name__ == "__main__":
    unittest.main()
