"""Tests for the Telegram dashboard. Run from trading_bot/:  python -m unittest -v

fastapi/uvicorn/pydantic/ccxt are stubbed when not installed, so the handler
logic can be tested without the web stack.
"""

import html.parser
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import config
import telegram_reporter as tg
from risk_manager import RiskManager


def _install_stubs():
    for name in ("ccxt", "uvicorn"):
        try:
            importlib.import_module(name)
        except ImportError:
            sys.modules[name] = types.ModuleType(name)
    try:
        importlib.import_module("fastapi")
    except ImportError:
        fastapi = types.ModuleType("fastapi")

        class FastAPI:
            def __init__(self, **kwargs):
                pass

            def get(self, _path):
                return lambda f: f

            post = get

        class HTTPException(Exception):
            def __init__(self, status_code, detail=None):
                super().__init__(detail)
                self.status_code = status_code

        fastapi.FastAPI, fastapi.HTTPException = FastAPI, HTTPException
        fastapi.Header = lambda default=None: default
        sys.modules["fastapi"] = fastapi
    try:
        importlib.import_module("pydantic")
    except ImportError:
        pydantic = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        pydantic.BaseModel = BaseModel
        sys.modules["pydantic"] = pydantic


_install_stubs()
_tmp = tempfile.TemporaryDirectory()
with mock.patch.object(config, "DAILY_STATE_FILE", str(Path(_tmp.name) / "import_state.json")):
    import main
from fastapi import HTTPException  # noqa: E402  (stub or real, after _install_stubs)


def tearDownModule():
    _tmp.cleanup()


class RecordingReporter(tg.TelegramReporter):
    """Real reporter with the HTTP call replaced by a recorder."""

    def __init__(self):
        super().__init__(token="123:abc", chat_id="42")
        self.calls = []

    def _call(self, method, payload):
        self.calls.append((method, payload))
        return True

    def messages(self):
        return [p for m, p in self.calls if m == "sendMessage"]


class FakeExecutor:
    dry_run = True

    def __init__(self, positions=None, close_fails=False):
        self.positions = positions or []
        self.close_fails = close_fails
        self.closed = False

    def get_open_positions(self):
        return list(self.positions)

    def close_all_positions(self):
        if self.close_fails:
            raise RuntimeError("exchange down")
        self.closed = True
        results = [{"symbol": p["symbol"], "status": "closed"} for p in self.positions]
        self.positions = []
        return results


def _assert_valid_html(testcase, text):
    """Telegram rejects unbalanced tags; check every opened tag is closed."""
    stack = []

    class P(html.parser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            stack.append(tag)

        def handle_endtag(self, tag):
            testcase.assertEqual(stack.pop(), tag)

    P().feed(text)
    testcase.assertEqual(stack, [])


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reporter = RecordingReporter()
        self.executor = FakeExecutor([{"symbol": "BTC/USDT", "side": "long", "contracts": 2.5}])
        self.risk = RiskManager(
            account_balance=1_000_000, max_daily_loss_pct=1.5,
            state_file=str(Path(self.tmp.name) / "state.json"),
            executor=self.executor, alert=self.reporter.send,
        )
        patches = [
            mock.patch.object(main, "reporter", self.reporter),
            mock.patch.object(main, "executor", self.executor),
            mock.patch.object(main, "risk", self.risk),
            mock.patch.object(config, "TELEGRAM_CHAT_ID", "42"),
            mock.patch.object(config, "TELEGRAM_WEBHOOK_SECRET", "s3cret"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def press(self, data, chat_id=42):
        return main.handle_telegram_update(
            {"callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}}}}
        )

    def last_text(self):
        return self.reporter.messages()[-1]["text"]


class TestKeyboard(unittest.TestCase):
    def test_layout(self):
        rows = tg.dashboard_keyboard()["inline_keyboard"]
        self.assertEqual(
            [[(b["text"], b["callback_data"]) for b in row] for row in rows],
            [
                [("📊 PNL יומי", "PNL"), ("🔓 פוזיציות פתוחות", "POSITIONS")],
                [("🛡️ סטטוס סיכון", "RISK"), ("🚨 KILL-SWITCH חירום", "KILL_SWITCH")],
            ],
        )

    def test_every_callback_has_a_handler(self):
        for kb in (tg.dashboard_keyboard(), tg.kill_confirm_keyboard()):
            for row in kb["inline_keyboard"]:
                for button in row:
                    self.assertIn(button["callback_data"], main.BUTTON_HANDLERS)
                    self.assertLessEqual(len(button["callback_data"].encode()), 64)  # Telegram limit


class TestFormatting(unittest.TestCase):
    def test_daily_summary(self):
        text = tg.format_daily_summary(12345.678, 12, 58.333, 2500, account_balance=1_000_000, date="2026-09-26")
        _assert_valid_html(self, text)
        for expected in ("סיכום יומי | Daily Summary", "2026-09-26", "+$12,345.68", "+1.23%",
                         "Trades: <b>12</b>", "Win rate: <b>58.33%</b>", "Drawdown: <b>$2,500.00</b>", "0.25%"):
            self.assertIn(expected, text)

    def test_negative_pnl(self):
        text = tg.format_daily_summary(-1500, 3, 0, 1500, account_balance=1_000_000, date="d")
        self.assertIn("🔴 P&amp;L: <b>-$1,500.00</b> (-0.15%)", text)

    def test_send_daily_summary_payload(self):
        r = RecordingReporter()
        r.send_daily_summary(100, 1, 100, 0, date="2026-09-26")
        (method, payload), = r.calls
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["chat_id"], "42")
        self.assertEqual(payload["reply_markup"], tg.dashboard_keyboard())

    def test_positions_escapes_dynamic_text(self):
        text = tg.format_positions([{"symbol": "<b>X</b>&", "side": "short", "contracts": 1,
                                     "entryPrice": 100, "unrealizedPnl": -5}])
        _assert_valid_html(self, text)
        self.assertIn("&lt;b&gt;X&lt;/b&gt;&amp;", text)
        self.assertIn("🟥 SHORT", text)
        self.assertIn("-$5.00", text)

    def test_all_builders_are_valid_html(self):
        for text in (
            tg.format_pnl(-100, 1_000_000),
            tg.format_positions([]),
            tg.format_risk(-7500, 15000, 1.5, False),
            tg.format_risk(-15000, 15000, 1.5, True),
            tg.format_kill_confirmation([{"symbol": "A", "status": "closed"},
                                         {"symbol": "B", "status": "error", "error": "<boom>"}]),
            tg.format_kill_confirmation([]),
        ):
            _assert_valid_html(self, text)

    def test_disabled_reporter_does_not_call_api(self):
        with mock.patch.object(tg.requests, "post") as post:
            self.assertFalse(tg.TelegramReporter("YOUR_TOKEN", "1").send_dashboard())
        post.assert_not_called()


class TestButtons(DashboardTestCase):
    def test_pnl(self):
        self.risk.record_pnl(2500)
        self.press("PNL")
        text = self.last_text()
        self.assertIn("+$2,500.00", text)
        self.assertIn("Base balance: $1,000,000.00", text)
        self.assertIn("Equity: <b>$1,002,500.00</b>", text)
        self.assertEqual(self.reporter.calls[0], ("answerCallbackQuery", {"callback_query_id": "cb1"}))

    def test_positions(self):
        self.press("POSITIONS")
        self.assertIn("BTC/USDT", self.last_text())
        self.assertIn("🟩 LONG", self.last_text())

    def test_positions_fetch_error_is_reported(self):
        self.executor.get_open_positions = mock.Mock(side_effect=RuntimeError("timeout"))
        with self.assertLogs("trading_bot", level="ERROR"):
            self.press("POSITIONS")
        self.assertIn("Failed to fetch positions", self.last_text())

    def test_risk(self):
        self.risk.record_pnl(-7500)
        self.press("RISK")
        text = self.last_text()
        self.assertIn("Daily loss: <b>$7,500.00</b> / $15,000.00 (1.50%)", text)
        self.assertIn("50%", text)
        self.assertIn("Remaining: <b>$7,500.00</b>", text)
        self.assertIn("OFF - trading enabled", text)

    def test_kill_switch_asks_for_confirmation_first(self):
        self.press("KILL_SWITCH")
        self.assertFalse(self.executor.closed)
        self.assertFalse(self.risk.kill_switch_active)
        self.assertEqual(self.reporter.messages()[-1]["reply_markup"], tg.kill_confirm_keyboard())

    def test_kill_switch_confirm(self):
        with self.assertLogs("risk_manager", level="CRITICAL"):
            self.press("KILL_CONFIRM")
        self.assertTrue(self.executor.closed)
        self.assertTrue(self.risk.kill_switch_active)
        text = self.last_text()
        self.assertIn("KILL-SWITCH הופעל | ACTIVATED", text)
        self.assertIn("Closed: <b>1</b>", text)
        self.assertIn("BTC/USDT", text)
        self.press("RISK")
        self.assertIn("ACTIVE - trading blocked", self.last_text())

    def test_kill_switch_close_failure(self):
        self.executor.close_fails = True
        with self.assertLogs("risk_manager", level="CRITICAL"):
            self.press("KILL_CONFIRM")
        self.assertTrue(self.risk.kill_switch_active)
        self.assertIn("EMERGENCY CLOSE FAILED", self.last_text())

    def test_kill_switch_cancel(self):
        self.press("KILL_CANCEL")
        self.assertFalse(self.executor.closed)
        self.assertIn("Cancelled", self.last_text())

    def test_unauthorized_chat_is_ignored(self):
        with self.assertLogs("trading_bot", level="WARNING"):
            self.press("KILL_CONFIRM", chat_id=999)
        self.assertFalse(self.executor.closed)
        self.assertEqual(self.reporter.calls, [("answerCallbackQuery", {"callback_query_id": "cb1", "text": "⛔ Unauthorized"})])

    def test_unknown_button(self):
        self.press("NOPE")
        self.assertEqual(self.reporter.messages(), [])


class TestCommands(DashboardTestCase):
    def command(self, text, chat_id=42):
        return main.handle_telegram_update({"message": {"text": text, "chat": {"id": chat_id}}})

    def test_menu(self):
        for cmd in ("/start", "/menu", "/dashboard@MyBot"):
            self.command(cmd)
            self.assertEqual(self.reporter.messages()[-1]["reply_markup"], tg.dashboard_keyboard())

    def test_summary(self):
        self.risk.record_pnl(1000)
        self.risk.record_pnl(-400)
        self.command("/summary")
        text = self.last_text()
        self.assertIn("+$600.00", text)
        self.assertIn("Trades: <b>2</b>", text)
        self.assertIn("Win rate: <b>50.00%</b>", text)
        self.assertIn("Drawdown: <b>$400.00</b>", text)

    def test_unauthorized_command(self):
        with self.assertLogs("trading_bot", level="WARNING"):
            self.command("/menu", chat_id=7)
        self.assertEqual(self.reporter.calls, [])


class TestWebhookAuth(DashboardTestCase):
    def test_rejects_bad_secret(self):
        for header in (None, "wrong", "סוד"):
            with self.subTest(header), self.assertRaises(HTTPException) as ctx:
                main.telegram_webhook({}, x_telegram_bot_api_secret_token=header)
            self.assertEqual(ctx.exception.status_code, 401)

    def test_refuses_placeholder_secret(self):
        with mock.patch.object(config, "TELEGRAM_WEBHOOK_SECRET", "YOUR_TELEGRAM_WEBHOOK_SECRET"):
            with self.assertRaises(HTTPException) as ctx:
                main.telegram_webhook({}, x_telegram_bot_api_secret_token="YOUR_TELEGRAM_WEBHOOK_SECRET")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_accepts_good_secret(self):
        self.assertEqual(main.telegram_webhook({"update_id": 1}, x_telegram_bot_api_secret_token="s3cret"), {"ok": True})

    def test_handler_crash_still_returns_200(self):
        with mock.patch.object(main, "handle_telegram_update", side_effect=RuntimeError("x")), \
                self.assertLogs("trading_bot", level="ERROR"):
            self.assertEqual(main.telegram_webhook({}, x_telegram_bot_api_secret_token="s3cret"), {"ok": False})

    def test_tradingview_refuses_placeholder_secret(self):
        signal = main.Signal(secret="YOUR_WEBHOOK_SECRET", symbol="BTC/USDT", side="buy", entry=100, stop=99)
        with mock.patch.object(config, "TRADINGVIEW_WEBHOOK_SECRET", "YOUR_WEBHOOK_SECRET"):
            with self.assertRaises(HTTPException) as ctx:
                main.webhook(signal)
        self.assertEqual(ctx.exception.status_code, 503)


class TestDayEndSummary(DashboardTestCase):
    def test_rollover_sends_previous_day_summary(self):
        self.risk.on_day_end = main._send_day_end_summary
        with mock.patch("risk_manager._utc_today", return_value="2026-09-26"):
            self.risk.check_rollover()
            self.risk._day = "2026-09-26"
            self.risk.record_pnl(3000)
            self.risk.record_pnl(-1000)
        with mock.patch("risk_manager._utc_today", return_value="2026-09-27"):
            self.risk.check_rollover()
            self.assertEqual(self.risk.daily_stats()["total_trades"], 0)
        text = self.last_text()
        self.assertIn("2026-09-26", text)
        self.assertIn("+$2,000.00", text)
        self.assertIn("Trades: <b>2</b>", text)
        self.assertIn("Drawdown: <b>$1,000.00</b>", text)


if __name__ == "__main__":
    unittest.main()
