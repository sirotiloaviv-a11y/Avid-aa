"""Tests for risk_manager. Run from trading_bot/:  python -m unittest -v"""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import risk_manager
from risk_manager import RiskManager


class FakeExecutor:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def close_all_positions(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("exchange down")
        return [{"symbol": "BTC/USDT", "status": "closed"}]


class RiskManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp.name) / "daily_state.json"
        self.executor = FakeExecutor()
        self.alerts = []

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, **kwargs):
        kwargs.setdefault("executor", self.executor)
        return RiskManager(
            account_balance=1_000_000,
            max_daily_loss_pct=1.5,
            max_risk_per_trade_pct=0.25,
            state_file=str(self.state_file),
            alert=self.alerts.append,
            **kwargs,
        )

    def on_day(self, day):
        return mock.patch.object(risk_manager, "_utc_today", return_value=day)


class TestPersistence(RiskManagerTestCase):
    def test_state_survives_restart(self):
        with self.on_day("2026-09-26"):
            rm = self.make()
            rm.record_pnl(-5000)
            restarted = self.make()
        self.assertEqual(restarted.daily_pnl, -5000)
        self.assertFalse(restarted.kill_switch_active)

    def test_kill_switch_survives_restart(self):
        with self.on_day("2026-09-26"):
            self.make().trigger_emergency_kill_switch("test")
            restarted = self.make()
            self.assertTrue(restarted.kill_switch_active)
            self.assertEqual(restarted.can_execute_trade("buy", 100, 99), (False, "kill switch active"))

    def test_state_file_contents(self):
        with self.on_day("2026-09-26"):
            self.make().record_pnl(-1234.5)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["date"], "2026-09-26")
        self.assertEqual(state["daily_pnl"], -1234.5)
        self.assertFalse(state["kill_switch_active"])

    def test_stale_file_from_previous_day_is_ignored(self):
        self.state_file.write_text(json.dumps(
            {"date": "2026-09-25", "daily_pnl": -20000, "kill_switch_active": True}
        ))
        with self.on_day("2026-09-26"):
            rm = self.make()
        self.assertEqual(rm.daily_pnl, 0.0)
        self.assertFalse(rm.kill_switch_active)

    def test_corrupt_file_fails_closed(self):
        self.state_file.write_text("{not json")
        with self.on_day("2026-09-26"):
            rm = self.make()
        self.assertTrue(rm.kill_switch_active)


class TestDailyReset(RiskManagerTestCase):
    def test_resets_pnl_and_kill_switch_at_utc_midnight(self):
        with self.on_day("2026-09-26"):
            rm = self.make()
            rm.record_pnl(-15000)  # breaches the limit -> kill switch
            self.assertTrue(rm.kill_switch_active)
        with self.on_day("2026-09-27"):
            self.assertEqual(rm.can_execute_trade("buy", 100, 99), (True, "ok"))
            self.assertEqual(rm.daily_pnl, 0.0)
            self.assertFalse(rm.kill_switch_active)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["date"], "2026-09-27")
        self.assertFalse(state["kill_switch_active"])

    def test_utc_today_uses_utc(self):
        self.assertRegex(risk_manager._utc_today(), r"^\d{4}-\d{2}-\d{2}$")


class TestStopLossEnforcement(RiskManagerTestCase):
    def setUp(self):
        super().setUp()
        self.rm = self.make()

    def test_valid_stops(self):
        self.assertEqual(self.rm.can_execute_trade("buy", 60000, 59000), (True, "ok"))
        self.assertEqual(self.rm.can_execute_trade("sell", 60000, 61000), (True, "ok"))

    def test_rejects_invalid_stops(self):
        cases = {
            "missing": ("buy", 60000, None),
            "zero": ("buy", 60000, 0),
            "negative": ("buy", 60000, -1),
            "nan": ("buy", 60000, float("nan")),
            "inf": ("sell", 60000, float("inf")),
            "string": ("buy", 60000, "59000"),
            "bool": ("buy", 60000, True),
            "equal to entry": ("buy", 60000, 60000),
            "buy stop above entry": ("buy", 60000, 61000),
            "sell stop below entry": ("sell", 60000, 59000),
        }
        for name, args in cases.items():
            with self.subTest(name):
                allowed, reason = self.rm.can_execute_trade(*args)
                self.assertFalse(allowed)
                self.assertTrue(reason)

    def test_rejects_bad_side_and_entry(self):
        self.assertFalse(self.rm.can_execute_trade("long", 100, 99)[0])
        self.assertFalse(self.rm.can_execute_trade("buy", None, 99)[0])

    def test_rejects_when_daily_limit_hit(self):
        self.rm.daily_pnl = -15000  # set directly, bypassing the auto kill switch
        self.assertEqual(self.rm.can_execute_trade("buy", 100, 99), (False, "daily loss limit reached"))


class TestKillSwitch(RiskManagerTestCase):
    def test_trigger_closes_positions_and_persists(self):
        rm = self.make()
        results = rm.trigger_emergency_kill_switch("manual")
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(results, [{"symbol": "BTC/USDT", "status": "closed"}])
        self.assertTrue(json.loads(self.state_file.read_text())["kill_switch_active"])
        self.assertTrue(any("EMERGENCY KILL SWITCH: manual" in a for a in self.alerts))
        self.assertEqual(rm.position_size(100, 99), 0.0)

    def test_logs_incident(self):
        rm = self.make()
        with self.assertLogs("risk_manager", level="CRITICAL") as logs:
            rm.trigger_emergency_kill_switch("manual")
        self.assertIn("EMERGENCY KILL SWITCH", logs.output[0])

    def test_daily_loss_breach_triggers_automatically(self):
        rm = self.make()
        rm.record_pnl(-10000)
        self.assertEqual(self.executor.calls, 0)
        rm.record_pnl(-5000)
        self.assertTrue(rm.kill_switch_active)
        self.assertEqual(self.executor.calls, 1)
        rm.record_pnl(-100)  # already active: don't fire again
        self.assertEqual(self.executor.calls, 1)

    def test_kill_switch_persisted_even_if_close_fails(self):
        rm = self.make(executor=FakeExecutor(fail=True))
        with self.assertLogs("risk_manager", level="CRITICAL"), self.assertRaises(RuntimeError):
            rm.trigger_emergency_kill_switch("manual")
        self.assertTrue(json.loads(self.state_file.read_text())["kill_switch_active"])
        self.assertTrue(any("FAILED" in a for a in self.alerts))

    def test_broken_alert_does_not_block_kill_switch(self):
        def broken(_):
            raise RuntimeError("telegram down")
        rm = RiskManager(state_file=str(self.state_file), executor=self.executor, alert=broken)
        with self.assertLogs("risk_manager", level="WARNING"):
            rm.trigger_emergency_kill_switch("manual")
        self.assertEqual(self.executor.calls, 1)


class TestExecutorCloseAll(unittest.TestCase):
    """Dry-run close_all_positions flattens what market_order opened."""

    def test_dry_run_flattens_positions(self):
        with mock.patch.dict(sys.modules, {"ccxt": sys.modules.get("ccxt") or types.ModuleType("ccxt")}):
            import execution
            ex = execution.OrderExecutor(dry_run=True)
            ex.market_order("BTC/USDT", "buy", 2.5)
            ex.market_order("ETH/USDT", "sell", 10)
            results = ex.close_all_positions()
        self.assertEqual({r["symbol"] for r in results}, {"BTC/USDT", "ETH/USDT"})
        self.assertTrue(all(r["status"] == "closed" for r in results))
        sides = {r["symbol"]: r["order"]["side"] for r in results}
        self.assertEqual(sides, {"BTC/USDT": "sell", "ETH/USDT": "buy"})
        self.assertEqual(ex._sim_positions, {})


if __name__ == "__main__":
    unittest.main()
