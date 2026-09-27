from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from trading_bot.risk_manager import (
    Direction,
    DrawdownWarningEvent,
    EconomicEvent,
    ExitReason,
    HaltEvent,
    HaltKind,
    Impact,
    NewsCheck,
    OpenTrade,
    RiskStatus,
    TradeClosedEvent,
    TradeOpenedEvent,
)
from trading_bot.telegram_bot.formatter import (
    fmt_money,
    fmt_pct,
    fmt_price,
    fmt_qty,
    format_daily_summary,
    format_drawdown_warning,
    format_halt,
    format_news,
    format_status,
    format_trade_entry,
    format_trade_exit,
    progress_bar,
    split_message,
)
from trading_bot.telegram_bot.notifier import html_to_plain

AT = datetime(2026, 3, 10, 14, 30, tzinfo=timezone.utc)


def status(account_id: str = "apex_nq_1", **overrides: object) -> RiskStatus:
    values: dict[str, object] = dict(
        account_id=account_id, trading_day=date(2026, 3, 10), balance=50_000.0,
        equity=49_700.0, last_update=AT, day_start_reference=50_000.0, daily_pnl=-300.0,
        daily_loss_floor=49_250.0, daily_room=450.0, drawdown_floor=47_500.0,
        drawdown_room=2_200.0, high_water_mark=50_000.0, open_risk=0.0, trades_today=2,
        realized_pnl_today=-300.0, wins_today=1, losses_today=1, closed_today=2,
        daily_loss_used_pct=40.0, open_trades=(), halted=False, halt_reasons=(),
        should_flatten=False, halted_until=None,
    )
    values.update(overrides)
    return RiskStatus(**values)  # type: ignore[arg-type]


class ValueFormattingTests(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(fmt_money(1234.5), "$1,234.50")
        self.assertEqual(fmt_money(-1234.5), "-$1,234.50")
        self.assertEqual(fmt_money(12.0, signed=True), "+$12.00")
        self.assertEqual(fmt_money(0.0, signed=True), "$0.00")
        self.assertEqual(fmt_money(None), "—")

    def test_pct_price_qty(self) -> None:
        self.assertEqual(fmt_pct(1.234), "1.23%")
        self.assertEqual(fmt_pct(-0.5, signed=True), "-0.50%")
        self.assertEqual(fmt_price(20000.25), "20,000.25")
        self.assertEqual(fmt_price(1.23456), "1.2346")
        self.assertEqual(fmt_price(0.00012345), "0.000123")
        self.assertEqual(fmt_qty(3.0), "3")
        self.assertEqual(fmt_qty(0.405), "0.405")

    def test_progress_bar_is_clamped(self) -> None:
        self.assertEqual(progress_bar(50), "▓▓▓▓▓░░░░░")
        self.assertEqual(progress_bar(250), "▓" * 10)
        self.assertEqual(progress_bar(-5), "░" * 10)


class EventFormattingTests(unittest.TestCase):
    def test_trade_entry_has_every_field(self) -> None:
        text = format_trade_entry(TradeOpenedEvent(
            account_id="apex_nq_1", trade_id="42", symbol="NQ", direction=Direction.LONG,
            entry_price=20000.0, stop_price=19985.0, take_profit=20030.0, quantity=2.0,
            risk_amount=608.0, risk_pct=1.216, balance=50_000.0, at=AT,
        ))
        for fragment in ("🟢", "LONG NQ", "apex_nq_1", "20,000.00", "19,985.00", "15.00 pts",
                         "20,030.00", "R:R 2.00", "Size: 2", "$608.00", "1.22%", "#42"):
            self.assertIn(fragment, text)

    def test_trade_entry_short_without_optional_fields(self) -> None:
        text = format_trade_entry(TradeOpenedEvent(
            "acc", "t", "BTCUSDT", Direction.SHORT, 60000.0, 60500.0, None, 0.405,
            202.5, None, None, AT,
        ))
        self.assertIn("🔴 <b>SHORT BTCUSDT</b>", text)
        self.assertIn("Take profit: —", text)
        self.assertIn("Size: 0.405", text)

    def test_trade_exit_win_and_loss(self) -> None:
        win = format_trade_exit(TradeClosedEvent(
            "acc", "t1", "NQ", Direction.LONG, 20000.0, 20030.0, 1200.0, 2.4,
            ExitReason.TAKE_PROFIT, 51_200.0, AT,
        ))
        self.assertIn("✅ <b>EXIT NQ</b> · Take profit", win)
        self.assertIn("+$1,200.00", win)
        self.assertIn("+2.40%", win)
        self.assertIn("Balance: $51,200.00", win)
        loss = format_trade_exit(TradeClosedEvent(
            "acc", "t2", None, None, None, None, -500.0, None, ExitReason.DAILY_HALT, None, AT,
        ))
        self.assertIn("❌", loss)
        self.assertIn("Daily halt", loss)
        self.assertIn("-$500.00", loss)

    def test_every_exit_reason_has_a_label(self) -> None:
        for reason in ExitReason:
            text = format_trade_exit(TradeClosedEvent(
                "a", "t", "NQ", None, None, 1.0, 0.0, 0.0, reason, None, AT))
            self.assertIn("➖", text)

    def test_drawdown_warning_levels(self) -> None:
        event = DrawdownWarningEvent("acc", 80, 83.0, -1245.0, 1500.0, 98_755.0, 98_500.0, AT)
        text = format_drawdown_warning(event)
        self.assertIn("🚨 <b>DAILY DRAWDOWN 80%</b>", text)
        self.assertIn("83% of daily limit used", text)
        self.assertIn("-$1,245.00", text)
        self.assertIn("Room left: <b>$255.00</b>", text)
        half = format_drawdown_warning(DrawdownWarningEvent("a", 50, 50.0, -750, 1500, 1, 0, AT))
        self.assertTrue(half.startswith("⚠️"))

    def test_halt_messages(self) -> None:
        until = datetime(2026, 3, 10, 21, 0, tzinfo=timezone.utc)
        daily = format_halt(HaltEvent("acc", HaltKind.DAILY_LOSS, "equity <= floor", AT, True), until)
        self.assertIn("DAILY LOSS LIMIT", daily)
        self.assertIn("2026-03-10 21:00 UTC", daily)
        self.assertIn("equity &lt;= floor", daily)  # escaped
        dd = format_halt(HaltEvent("acc", HaltKind.MAX_DRAWDOWN, "x", AT, True))
        self.assertIn("until an operator clears it", dd)

    def test_user_text_is_escaped(self) -> None:
        text = format_trade_entry(TradeOpenedEvent(
            "<b>evil</b>", "t&1", "NQ", None, None, None, None, None, 0.0, None, None, AT))
        self.assertIn("&lt;b&gt;evil&lt;/b&gt;", text)
        self.assertIn("#t&amp;1", text)


class ReplyFormattingTests(unittest.TestCase):
    def test_status_lists_accounts_open_trades_and_halts(self) -> None:
        trade = OpenTrade("t1", "NQ", 300.0, AT.isoformat(), "long", 20000.0, 19985.0, 20030.0, 1.0)
        halted = status("ftmo_1", halted=True, halt_reasons=("daily loss limit hit",),
                        open_trades=(trade,), open_risk=300.0)
        text = format_status([status(), halted], kill_switch_active=True, now=AT)
        self.assertIn("KILL SWITCH ACTIVE", text)
        self.assertIn("<b>apex_nq_1</b> · 🟢 OK", text)
        self.assertIn("<b>ftmo_1</b> · 🛑 HALTED", text)
        self.assertIn("LONG NQ 1 @ 20,000.00", text)
        self.assertIn("! daily loss limit hit", text)
        self.assertIn("40%", text)

    def test_status_without_snapshot(self) -> None:
        text = format_status([status(last_update=None, equity=None, daily_pnl=None,
                                     daily_loss_used_pct=None)], kill_switch_active=False, now=AT)
        self.assertIn("no account snapshot yet", text)

    def test_news(self) -> None:
        cpi = EconomicEvent("CPI m/m", "USD", AT, Impact.HIGH)
        text = format_news([cpi], NewsCheck(False, "news blackout: USD CPI m/m"), enabled=True, now=AT)
        self.assertIn("⛔ news blackout", text)
        self.assertIn("<b>14:30</b> UTC · USD · CPI m/m", text)
        self.assertIn("No high-impact", format_news([], NewsCheck(True), enabled=True, now=AT))
        self.assertIn("disabled", format_news([], NewsCheck(True), enabled=False, now=AT))

    def test_daily_summary_aggregates_accounts(self) -> None:
        accounts = [
            status("a", trades_today=3, closed_today=3, wins_today=2, daily_pnl=400.0,
                   realized_pnl_today=400.0),
            status("b", trades_today=2, closed_today=2, wins_today=1, daily_pnl=-100.0,
                   realized_pnl_today=-150.0),
            status("c", trades_today=0, closed_today=0, wins_today=0, daily_pnl=None,
                   realized_pnl_today=0.0, halted=True),
        ]
        text = format_daily_summary(accounts, date(2026, 3, 10))
        self.assertIn("Daily summary · 2026-03-10", text)
        self.assertIn("Trades: <b>5</b> · closed 5 · win rate 60%", text)
        self.assertIn("Realized P&amp;L: <b>+$250.00</b>", text)
        self.assertIn("Day P&amp;L (equity): <b>+$300.00</b>", text)
        self.assertIn("<code>c</code> 🛑: 0 trades · win —", text)

    def test_summary_with_no_trades(self) -> None:
        text = format_daily_summary([status(trades_today=0, closed_today=0, wins_today=0)], None)
        self.assertIn("win rate —", text)


class SplitTests(unittest.TestCase):
    def test_short_message_untouched(self) -> None:
        self.assertEqual(split_message("a\nb"), ["a\nb"])

    def test_splits_on_line_boundaries(self) -> None:
        text = "\n".join(f"line {i:03d}" for i in range(100))
        chunks = split_message(text, limit=100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual("\n".join(chunks), text)

    def test_hard_cuts_overlong_line(self) -> None:
        chunks = split_message("x" * 250, limit=100)
        self.assertEqual([len(c) for c in chunks], [100, 100, 50])

    def test_html_to_plain(self) -> None:
        self.assertEqual(html_to_plain("<b>P&amp;L</b> &lt;3"), "P&L <3")


if __name__ == "__main__":
    unittest.main()
