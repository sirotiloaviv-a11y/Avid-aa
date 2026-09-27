from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading_bot.config import AccountConfig, ConfigError, NewsConfig, RiskLimits, SessionConfig, settings_from_env
from trading_bot.risk_manager import (
    Direction,
    DrawdownWarningEvent,
    EconomicEvent,
    ExitReason,
    HaltEvent,
    Impact,
    NewsGuard,
    OperatorControls,
    RiskEngine,
    RiskEvent,
    RiskManager,
    TradeClosedEvent,
    TradeOpenedEvent,
)
from trading_bot.config import Secret
from trading_bot.telegram_bot import (
    CommandProcessor,
    CommandResponder,
    DailySummaryScheduler,
    ParsedCommand,
    TelegramApiError,
    TelegramClient,
    TelegramNotifier,
    parse_command,
)
from trading_bot.utils import StateStore

T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
TOKEN = "123456:ABCdefGhIJKlmnoPQRstuVWXyz0123456789"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeTransport:
    """Records Bot API calls; replies from a script, else ``{"ok": true}``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replies: list[tuple[int, dict[str, Any]] | Exception] = []
        self.updates: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
        method = url.rsplit("/", 1)[1]
        params = json.loads(body)
        self.calls.append((method, params))
        if self.replies:
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply[0], json.dumps(reply[1]).encode()
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return 200, json.dumps({"ok": True, "result": updates}).encode()
        return 200, json.dumps({"ok": True, "result": {}}).encode()

    def sent(self) -> list[dict[str, Any]]:
        return [p for m, p in self.calls if m == "sendMessage"]


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name) / "state.db")
        self.clock = Clock(T0)
        self.transport = FakeTransport()
        self.client = TelegramClient(Secret(TOKEN), transport=self.transport)
        self.notifier = TelegramNotifier(self.client, ["111"], max_backoff=0)
        self.kill = Path(self.tmp.name) / "KILL"
        limits = RiskLimits(max_trades_per_day=10)
        self.manager = RiskManager({
            acc: RiskEngine(AccountConfig(acc, 100_000.0), limits, SessionConfig(), self.store,
                            kill_switch_path=self.kill, clock=self.clock)
            for acc in ("a1", "a2", "a3")
        })

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def texts(self) -> list[str]:
        self.notifier.flush()
        return [str(p["text"]) for p in self.transport.sent()]


class ParseCommandTests(unittest.TestCase):
    def test_plain_and_arguments(self) -> None:
        self.assertEqual(parse_command("/status"), ParsedCommand("status"))
        self.assertEqual(parse_command("  /HALT  news spike  "), ParsedCommand("halt", "news spike"))
        self.assertEqual(parse_command("/halt line1\nline2"), ParsedCommand("halt", "line1\nline2"))

    def test_bot_mentions(self) -> None:
        self.assertEqual(parse_command("/status@PropBot", "propbot"), ParsedCommand("status"))
        self.assertIsNone(parse_command("/status@OtherBot", "PropBot"))
        self.assertEqual(parse_command("/status@AnyBot"), ParsedCommand("status"))

    def test_not_commands(self) -> None:
        for text in (None, "", "status", "hello /status", "/", "/ status", "//status"):
            self.assertIsNone(parse_command(text), text)


class ClientTests(Fixture):
    def test_error_carries_retry_after_and_hides_token(self) -> None:
        self.transport.replies = [(429, {"ok": False, "error_code": 429, "description": "Too Many",
                                         "parameters": {"retry_after": 7}})]
        with self.assertRaises(TelegramApiError) as ctx:
            self.client.send_message("1", "x")
        self.assertEqual(ctx.exception.retry_after, 7)
        self.assertTrue(ctx.exception.retryable)
        self.transport.replies = [OSError(f"failed https://api.telegram.org/bot{TOKEN}/sendMessage")]
        with self.assertRaises(TelegramApiError) as ctx:
            self.client.send_message("1", "x")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_token_not_in_repr(self) -> None:
        self.assertNotIn(TOKEN, repr(self.client.__dict__))


class NotifierTests(Fixture):
    def test_retries_then_delivers(self) -> None:
        self.transport.replies = [OSError("down"), (502, {"ok": False, "error_code": 502})]
        self.notifier.send("<b>hi</b>")
        self.notifier.flush()
        # Two failed attempts, then success; nothing further queued.
        self.assertEqual([p["text"] for p in self.transport.sent()], ["<b>hi</b>"] * 3)
        self.assertEqual(self.transport.replies, [])

    def test_bad_markup_falls_back_to_plain_text(self) -> None:
        self.transport.replies = [(400, {"ok": False, "error_code": 400,
                                         "description": "can't parse entities"})]
        self.notifier.send("<b>P&amp;L</b>")
        self.notifier.flush()
        last = self.transport.sent()[-1]
        self.assertEqual((last["text"], last["parse_mode"]), ("P&L", ""))

    def test_gives_up_on_permanent_error(self) -> None:
        self.transport.replies = [(403, {"ok": False, "error_code": 403, "description": "blocked"})]
        self.notifier.send("x")
        self.notifier.flush()
        self.assertEqual(len(self.transport.sent()), 1)

    def test_background_worker_delivers_in_order(self) -> None:
        self.notifier.start()
        for i in range(5):
            self.notifier.send(f"m{i}")
        self.notifier.stop()
        self.assertEqual([p["text"] for p in self.transport.sent()], [f"m{i}" for i in range(5)])

    def test_listener_never_raises(self) -> None:
        self.notifier.handle_event("not an event")  # type: ignore[arg-type]


class EngineIntegrationTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.notifier.attach(self.manager)
        self.engine = self.manager["a1"]
        self.events: list[RiskEvent] = []
        self.engine.subscribe(self.events.append)

    def test_trade_entry_and_exit_alerts(self) -> None:
        self.engine.update_account(100_000, 100_000)
        self.engine.record_trade_opened("t1", "NQ", 404.0, direction=Direction.LONG,
                                        entry_price=20000.0, stop_price=19980.0,
                                        take_profit=20040.0, quantity=1)
        self.engine.record_trade_closed("t1", 800.0, exit_price=20040.0,
                                        reason=ExitReason.TAKE_PROFIT, balance=100_800.0)
        opened, closed = self.events
        assert isinstance(opened, TradeOpenedEvent) and isinstance(closed, TradeClosedEvent)
        self.assertAlmostEqual(opened.risk_pct or 0, 0.404)
        self.assertEqual(closed.symbol, "NQ")
        self.assertEqual(closed.entry_price, 20000.0)
        self.assertAlmostEqual(closed.pnl_pct or 0, 0.8)
        texts = self.texts()
        self.assertIn("LONG NQ", texts[0])
        self.assertIn("Take profit", texts[1])
        status = self.engine.status()
        self.assertEqual((status.wins_today, status.closed_today), (1, 1))

    def test_drawdown_warnings_at_50_80_then_halt(self) -> None:
        self.engine.update_account(100_000, 100_000)
        self.engine.update_account(100_000, 99_300)   # 46.7% of $1,500
        self.engine.update_account(100_000, 99_250)   # 50%
        self.engine.update_account(100_000, 99_200)   # 53%: no repeat
        self.engine.update_account(100_000, 98_800)   # 80%
        self.engine.update_account(100_000, 98_500)   # 100%: halt
        kinds = [(type(e).__name__, getattr(e, "level_pct", None)) for e in self.events]
        self.assertEqual(kinds, [("DrawdownWarningEvent", 50), ("DrawdownWarningEvent", 80),
                                 ("HaltEvent", None)])
        texts = self.texts()
        self.assertIn("DAILY DRAWDOWN 50%", texts[0])
        self.assertIn("DAILY DRAWDOWN 80%", texts[1])
        self.assertIn("TRADING HALTED", texts[2])
        self.assertIn("Resumes after the daily reset", texts[2])

    def test_warnings_not_repeated_after_restart(self) -> None:
        self.engine.update_account(100_000, 100_000)
        self.engine.update_account(100_000, 99_200)
        restarted = RiskEngine(AccountConfig("a1", 100_000.0), RiskLimits(), SessionConfig(),
                               self.store, clock=self.clock)
        events: list[RiskEvent] = []
        restarted.subscribe(events.append)
        restarted.update_account(100_000, 99_150)
        self.assertEqual(events, [])

    def test_drop_through_floor_sends_only_halt(self) -> None:
        self.engine.update_account(100_000, 100_000)
        self.engine.update_account(100_000, 98_000)
        self.assertEqual([type(e) for e in self.events], [HaltEvent])

    def test_warnings_reset_next_day(self) -> None:
        self.engine.update_account(100_000, 100_000)
        self.engine.update_account(100_000, 99_200)
        self.clock.now = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
        self.engine.update_account(99_200, 99_200)
        self.engine.update_account(99_200, 98_400)
        warnings = [e for e in self.events if isinstance(e, DrawdownWarningEvent)]
        self.assertEqual(len(warnings), 2)


class CommandProcessorTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        cpi = EconomicEvent("CPI m/m", "USD", T0 + timedelta(hours=2), Impact.HIGH)

        class Provider:
            def fetch(self) -> list[EconomicEvent]:
                return [cpi]

        guard = NewsGuard(Provider(), NewsConfig(), clock=self.clock)
        self.processor = CommandProcessor(OperatorControls(self.manager, self.kill), guard, clock=self.clock)
        for engine in self.manager:
            engine.update_account(100_000, 100_000)

    def run_cmd(self, text: str) -> str:
        command = parse_command(text)
        assert command is not None
        return self.processor.handle(command, operator="tester")

    def test_status(self) -> None:
        reply = self.run_cmd("/status")
        for acc in ("a1", "a2", "a3"):
            self.assertIn(f"<b>{acc}</b>", reply)

    def test_news(self) -> None:
        self.assertIn("CPI m/m", self.run_cmd("/news"))

    def test_halt_and_resume(self) -> None:
        reply = self.run_cmd("/halt fat finger")
        self.assertIn("EMERGENCY HALT", reply)
        self.assertTrue(self.kill.exists())
        self.assertIn("telegram:tester: fat finger", self.kill.read_text())
        for engine in self.manager:
            self.assertFalse(engine.check_new_trade().allowed)
        reply = self.run_cmd("/resume")
        self.assertFalse(self.kill.exists())
        self.assertIn("All accounts may trade", reply)
        for engine in self.manager:
            self.assertTrue(engine.check_new_trade().allowed)

    def test_resume_keeps_risk_halts(self) -> None:
        self.manager["a2"].update_account(100_000, 98_000)
        reply = self.run_cmd("/resume")
        self.assertIn("Still halted", reply)
        self.assertIn("a2", reply)
        self.assertFalse(self.manager["a2"].check_new_trade().allowed)

    def test_unknown_and_help(self) -> None:
        self.assertIn("Unknown command /foo", self.run_cmd("/foo"))
        self.assertIn("/halt", self.run_cmd("/help"))


class ResponderTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        processor = CommandProcessor(OperatorControls(self.manager, self.kill), None, clock=self.clock)
        self.responder = CommandResponder(self.client, processor, self.notifier, ["111"],
                                          self.store, clock=self.clock)

    def update(self, update_id: int, text: str, chat: int = 111, age: int = 0) -> dict[str, Any]:
        return {"update_id": update_id, "message": {
            "chat": {"id": chat}, "from": {"id": 5, "username": "op"}, "text": text,
            "date": int((self.clock.now - timedelta(seconds=age)).timestamp())}}

    def test_authorised_command_is_answered_in_that_chat(self) -> None:
        self.responder.handle_update(self.update(10, "/status"))
        self.notifier.flush()
        sent = self.transport.sent()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["chat_id"], "111")
        self.assertIn("Status", sent[0]["text"])
        self.assertEqual(self.store.get_value("telegram.update_offset"), "11")

    def test_unauthorised_chat_is_ignored_silently(self) -> None:
        self.responder.handle_update(self.update(11, "/halt", chat=999))
        self.assertEqual(self.texts(), [])
        self.assertFalse(self.kill.exists())
        self.assertEqual(self.store.get_value("telegram.update_offset"), "12")

    def test_stale_command_is_not_executed(self) -> None:
        self.responder.handle_update(self.update(12, "/halt", age=600))
        self.assertFalse(self.kill.exists())
        self.assertIn("too old", self.texts()[0])

    def test_first_start_skips_backlog(self) -> None:
        self.transport.updates = [self.update(40, "/halt"), self.update(41, "/resume")]
        self.responder.skip_backlog()
        self.assertFalse(self.kill.exists())
        self.assertEqual(self.store.get_value("telegram.update_offset"), "42")

    def test_poll_uses_saved_offset(self) -> None:
        self.responder.skip_backlog()
        self.transport.updates = [self.update(7, "/help")]
        self.responder._offset = 7
        self.responder.poll_once()
        self.assertEqual(self.transport.calls[-1][1].get("offset"), 7)
        self.assertIn("Trading bot commands", self.texts()[0])


class SchedulerTests(Fixture):
    def test_fires_once_just_before_reset(self) -> None:
        scheduler = DailySummaryScheduler(self.manager, self.notifier, SessionConfig(), self.store,
                                          lead_minutes=1, clock=self.clock)
        # 17:00 New York = 21:00 UTC on 2026-03-10 (DST).
        self.assertFalse(scheduler.tick(datetime(2026, 3, 10, 20, 58, tzinfo=timezone.utc)))
        self.assertTrue(scheduler.tick(datetime(2026, 3, 10, 20, 59, tzinfo=timezone.utc)))
        self.assertFalse(scheduler.tick(datetime(2026, 3, 10, 20, 59, 30, tzinfo=timezone.utc)))
        texts = self.texts()
        self.assertEqual(len(texts), 1)
        self.assertIn("Daily summary · 2026-03-10", texts[0])
        # Next day fires again.
        self.assertTrue(scheduler.tick(datetime(2026, 3, 11, 20, 59, tzinfo=timezone.utc)))


class TelegramConfigTests(unittest.TestCase):
    def test_parses_and_validates(self) -> None:
        s = settings_from_env({"ACCOUNTS": "a:1000", "TELEGRAM_BOT_TOKEN": TOKEN,
                               "TELEGRAM_CHAT_IDS": "111,-100222", "DAILY_LOSS_WARN_LEVELS": "80,50,70"})
        self.assertTrue(s.telegram.enabled)
        self.assertEqual(s.telegram.chat_ids, ("111", "-100222"))
        self.assertEqual(s.risk.daily_warning_levels, (50, 70, 80))
        self.assertNotIn(TOKEN, repr(s))
        self.assertFalse(settings_from_env({"ACCOUNTS": "a:1000"}).telegram.enabled)

    def test_rejects_bad_values(self) -> None:
        for env in ({"TELEGRAM_BOT_TOKEN": TOKEN}, {"TELEGRAM_BOT_TOKEN": "nope", "TELEGRAM_CHAT_IDS": "1"},
                    {"TELEGRAM_CHAT_IDS": "@channel"}, {"DAILY_LOSS_WARN_LEVELS": "50,120"}):
            with self.assertRaises(ConfigError, msg=str(env)):
                settings_from_env({"ACCOUNTS": "a:1000", **env})


if __name__ == "__main__":
    unittest.main()
