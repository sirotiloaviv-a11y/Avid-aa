from __future__ import annotations

import base64
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading_bot.config import AccountConfig, DashboardConfig, RiskLimits, Secret, SessionConfig
from trading_bot.dashboard import AuthThrottle, DashboardApp, DashboardServer, Request
from trading_bot.risk_manager import Direction, ExitReason, OperatorControls, RiskEngine, RiskManager
from trading_bot.utils import StateStore

T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery"


def basic(user: str = "admin", password: str = PASSWORD) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class ApiFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name) / "state.db")
        self.kill = Path(self.tmp.name) / "KILL"
        self.clock = Clock()
        self.manager = RiskManager({
            acc: RiskEngine(AccountConfig(acc, 100_000.0), RiskLimits(max_trades_per_day=10),
                            SessionConfig(), self.store, kill_switch_path=self.kill, clock=self.clock)
            for acc in ("acc1", "acc2", "acc3")
        })
        for engine in self.manager:
            engine.update_account(100_000, 100_000)
        self.controls = OperatorControls(self.manager, self.kill)
        self.fail_clock = [0.0]
        self.app = DashboardApp(
            manager=self.manager, controls=self.controls, store=self.store, news_guard=None,
            config=DashboardConfig(password=Secret(PASSWORD)), environment="paper",
            stale_after=timedelta(seconds=120), clock=self.clock,
            throttle=AuthThrottle(max_failures=3, window=60, clock=lambda: self.fail_clock[0]),
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def get(self, path: str, *, auth: str | None = None, client: str = "1.2.3.4") -> Any:
        headers = {"authorization": auth if auth is not None else basic(), "host": "localhost:8080"}
        return self.app.handle(Request("GET", path, headers, b"", client))

    def post(self, path: str, body: Any = None, *, headers: dict[str, str] | None = None) -> Any:
        base = {"authorization": basic(), "host": "localhost:8080",
                "content-type": "application/json", "x-dashboard-request": "1"}
        base.update(headers or {})
        data = json.dumps(body if body is not None else {}).encode()
        return self.app.handle(Request("POST", path, base, data, "1.2.3.4"))

    @staticmethod
    def body(response: Any) -> Any:
        return json.loads(response.body)


class AuthTests(ApiFixture):
    def test_healthz_is_public(self) -> None:
        self.assertEqual(self.get("/healthz", auth="").status, 200)

    def test_requires_basic_auth(self) -> None:
        response = self.get("/api/state", auth="")
        self.assertEqual(response.status, 401)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])
        # Separate addresses, so the lockout (tested below) doesn't kick in.
        for i, auth in enumerate((basic(password="wrong"), "Basic !!!notbase64", "Bearer " + PASSWORD)):
            self.assertEqual(self.get("/api/state", auth=auth, client=f"10.0.0.{i}").status, 401)
        self.assertEqual(self.get("/api/state").status, 200)

    def test_lockout_after_repeated_failures(self) -> None:
        for _ in range(3):
            self.get("/api/state", auth=basic(password="nope"))
        self.assertEqual(self.get("/api/state").status, 429)  # even the right password
        self.assertEqual(self.get("/api/state", client="5.6.7.8").status, 200)  # per address
        self.fail_clock[0] = 61
        self.assertEqual(self.get("/api/state").status, 200)

    def test_dashboard_refuses_to_start_without_password(self) -> None:
        with self.assertRaises(ValueError):
            DashboardApp(manager=self.manager, controls=self.controls, store=self.store,
                         news_guard=None, config=DashboardConfig(), environment="paper",
                         stale_after=timedelta(seconds=1))


class ReadRouteTests(ApiFixture):
    def test_index_and_static(self) -> None:
        index = self.get("/")
        self.assertEqual(index.status, 200)
        self.assertIn(b"KILL SWITCH", index.body)
        self.assertTrue(self.get("/static/app.js").content_type.startswith("text/javascript"))
        self.assertEqual(self.get("/static/../app.py").status, 404)
        self.assertEqual(self.get("/static/%2e%2e/app.py").status, 404)
        self.assertEqual(self.get("/nope").status, 404)

    def test_state(self) -> None:
        engine = self.manager["acc1"]
        engine.record_trade_opened("t1", "NQ", 404.0, direction=Direction.LONG, entry_price=20000.0,
                                   stop_price=19980.0, quantity=1)
        engine.record_trade_closed("t1", -404.0, exit_price=19980.0, reason=ExitReason.STOP_LOSS)
        engine.update_account(100_000, 99_000)
        state = self.body(self.get("/api/state"))
        self.assertEqual(state["overall"]["status"], "ACTIVE")
        self.assertEqual(state["overall"]["total_equity"], 299_000.0)
        self.assertEqual([a["id"] for a in state["accounts"]], ["acc1", "acc2", "acc3"])
        acc1 = state["accounts"][0]
        self.assertEqual(acc1["badge"], "ACTIVE")
        self.assertAlmostEqual(acc1["daily"]["used_pct"], 66.7)
        self.assertEqual(state["trades"][0]["status"], "SL")
        self.assertEqual(state["trades"][0]["pnl"], -404.0)
        self.assertEqual(state["news"]["enabled"], False)
        self.assertTrue(any(e["kind"] == "warning" for e in state["activity"]))

    def test_trades_endpoint_filters(self) -> None:
        self.manager["acc1"].record_trade_opened("a", "NQ", 10.0)
        self.manager["acc2"].record_trade_opened("b", "MNQ", 10.0)
        trades = self.body(self.get("/api/trades?account=acc2&limit=5"))["trades"]
        self.assertEqual([t["trade_id"] for t in trades], ["b"])
        self.assertEqual(self.get("/api/trades?limit=abc").status, 400)


class ControlRouteTests(ApiFixture):
    def test_kill_switch_and_resume(self) -> None:
        response = self.post("/api/kill", {"reason": "flash crash"})
        self.assertEqual(response.status, 200, response.body)
        self.assertTrue(self.kill.exists())
        for engine in self.manager:
            self.assertFalse(engine.check_new_trade().allowed)
            self.assertTrue(engine.status().should_flatten)
        state = self.body(self.get("/api/state"))
        self.assertEqual(state["overall"]["status"], "HALTED")
        self.assertTrue(state["overall"]["kill_switch"])
        self.assertEqual({a["badge"] for a in state["accounts"]}, {"HALTED"})

        self.assertEqual(self.post("/api/resume").status, 200)
        self.assertFalse(self.kill.exists())
        for engine in self.manager:
            self.assertTrue(engine.check_new_trade().allowed)

    def test_account_pause_toggle(self) -> None:
        self.assertEqual(self.post("/api/accounts/acc2/pause").status, 200)
        acc2 = self.manager["acc2"]
        self.assertFalse(acc2.check_new_trade().allowed)
        self.assertFalse(acc2.status().should_flatten)  # pause keeps positions
        self.assertTrue(self.manager["acc1"].check_new_trade().allowed)
        self.assertEqual(self.body(self.get("/api/state"))["accounts"][1]["badge"], "PAUSED")
        # Global resume does not undo an individual pause.
        self.post("/api/resume")
        self.assertFalse(acc2.check_new_trade().allowed)
        self.assertEqual(self.post("/api/accounts/acc2/unpause").status, 200)
        self.assertTrue(acc2.check_new_trade().allowed)

    def test_unknown_account(self) -> None:
        self.assertEqual(self.post("/api/accounts/ghost/pause").status, 404)

    def test_csrf_protection(self) -> None:
        self.assertEqual(self.post("/api/kill", headers={"x-dashboard-request": ""}).status, 403)
        self.assertEqual(self.post("/api/kill", headers={"content-type": "text/plain"}).status, 403)
        self.assertEqual(self.post("/api/kill", headers={"origin": "https://evil.example"}).status, 403)
        self.assertFalse(self.kill.exists())
        self.assertEqual(self.post("/api/kill", headers={"origin": "http://localhost:8080"}).status, 200)

    def test_bad_bodies(self) -> None:
        base = {"authorization": basic(), "host": "h", "content-type": "application/json",
                "x-dashboard-request": "1"}
        bad_json = self.app.handle(Request("POST", "/api/kill", base, b"{nope", "1"))
        self.assertEqual(bad_json.status, 400)
        not_object = self.app.handle(Request("POST", "/api/kill", base, b"[1]", "1"))
        self.assertEqual(not_object.status, 400)
        too_big = self.app.handle(Request("POST", "/api/kill", base, b" " * 5000, "1"))
        self.assertEqual(too_big.status, 413)
        self.assertFalse(self.kill.exists())
        put = self.app.handle(Request("PUT", "/api/kill", base, b"{}", "1"))
        self.assertEqual(put.status, 405)

    def test_controls_signal_live_clients(self) -> None:
        seen = self.app.wait_for_change(-1, 0)
        self.post("/api/accounts/acc1/pause")
        self.assertNotEqual(self.app.wait_for_change(seen, 0), seen)


class LiveServerTests(ApiFixture):
    def test_real_http_server_and_event_stream(self) -> None:
        server = DashboardServer(self.app, "127.0.0.1", 0)
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        try:
            request = urllib.request.Request(base + "/api/state", headers={"Authorization": basic()})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                self.assertEqual(json.load(response)["overall"]["accounts"], 3)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base + "/api/state", timeout=5)
            self.assertEqual(ctx.exception.code, 401)

            stream = urllib.request.urlopen(urllib.request.Request(
                base + "/api/stream", headers={"Authorization": basic()}), timeout=5)
            self.assertEqual(stream.headers["Content-Type"], "text/event-stream")
            self.assertEqual(stream.readline(), b"event: state\n")
            first = json.loads(stream.readline().removeprefix(b"data: "))
            self.assertEqual(first["overall"]["status"], "ACTIVE")
            stream.readline()
            # A kill from another client is pushed to the open stream.
            post = urllib.request.Request(
                base + "/api/kill", data=b"{}", method="POST",
                headers={"Authorization": basic(), "Content-Type": "application/json",
                         "X-Dashboard-Request": "1"})
            with urllib.request.urlopen(post, timeout=5) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(stream.readline(), b"event: state\n")
            second = json.loads(stream.readline().removeprefix(b"data: "))
            self.assertEqual(second["overall"]["status"], "HALTED")
            stream.close()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
