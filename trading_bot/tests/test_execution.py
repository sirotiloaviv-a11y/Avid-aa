from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_bot.brokers import (
    AccountSnapshot,
    Broker,
    BrokerError,
    ClosedTrade,
    OrderAck,
    OrderRequest,
    PaperBroker,
    Position,
    TradeRef,
    bracket_prices,
)
from trading_bot.config import AccountConfig, RiskLimits, SessionConfig
from trading_bot.risk_manager import (
    AssetClass,
    Direction,
    ExitReason,
    RiskEngine,
    RiskEvent,
    RiskManager,
    TradeClosedEvent,
    TradeOpenedEvent,
    get_instrument,
)
from trading_bot.strategies import AccountRoute, Candle, ExecutionEngine, ExecutionStatus, Side, Signal
from trading_bot.utils import StateStore

T0 = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
M5 = timedelta(minutes=5)
NQ = get_instrument("NQ")
BTC = get_instrument("BTCUSDT")
REF = TradeRef(Direction.LONG, 2.0, 20000.25)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def bar(symbol: str, o: float, h: float, low: float, c: float, start: datetime = T0) -> Candle:
    return Candle(symbol, start, M5, o, h, low, c)


def order(account: str = "acc", direction: Direction = Direction.LONG, qty: str = "2",
          stop: str = "19980", tp: str | None = "20040") -> OrderRequest:
    return OrderRequest(account, NQ, direction, Decimal(qty), Decimal(stop),
                        Decimal(tp) if tp else None, "t1", 20000.0)


class PaperBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.broker = PaperBroker({"acc": 50_000.0}, slippage_ticks=1, clock=self.clock)
        self.broker.set_price("NQ", 20000.0)

    def test_fill_with_slippage_and_snapshot(self) -> None:
        ack = self.broker.place_bracket(order())
        self.assertEqual(ack.fill_price, 20000.25)  # one tick against us
        self.assertEqual(self.broker.positions("acc")["NQ"], Position("NQ", 2.0, 20000.25))
        self.broker.set_price("NQ", 20010.25)
        snap = self.broker.account_snapshot("acc")
        self.assertEqual(snap, AccountSnapshot(50_000.0, 50_000.0 + 10 * 20 * 2))  # $20/pt, 2 contracts

    def test_stop_hit_charges_slippage_and_fees(self) -> None:
        self.broker.place_bracket(order())
        self.broker.on_candle(bar("NQ", 20000, 20005, 19975, 19990, T0 + M5))
        self.assertEqual(self.broker.positions("acc"), {})
        closed = self.broker.closed_trade("acc", "NQ", T0, REF)
        assert closed is not None
        self.assertEqual(closed.exit_price, 19979.75)
        # (19979.75 - 20000.25) * $20 * 2 - $4 * 2 fees
        self.assertAlmostEqual(closed.realized_pnl, -20.5 * 20 * 2 - 8)
        self.assertAlmostEqual(self.broker.account_snapshot("acc").balance, 50_000 + closed.realized_pnl)

    def test_target_hit(self) -> None:
        self.broker.place_bracket(order())
        self.broker.on_candle(bar("NQ", 20010, 20045, 20005, 20030, T0 + M5))
        closed = self.broker.closed_trade("acc", "NQ", T0, REF)
        assert closed is not None
        self.assertEqual(closed.exit_price, 20040.0)

    def test_stop_assumed_first_when_bar_touches_both(self) -> None:
        self.broker.place_bracket(order())
        self.broker.on_candle(bar("NQ", 20000, 20050, 19970, 20000, T0 + M5))
        closed = self.broker.closed_trade("acc", "NQ", T0, REF)
        assert closed is not None
        self.assertLess(closed.realized_pnl, 0)

    def test_gap_through_stop_fills_at_open(self) -> None:
        self.broker.place_bracket(order())
        self.broker.on_candle(bar("NQ", 19950, 19960, 19940, 19955, T0 + M5))
        closed = self.broker.closed_trade("acc", "NQ", T0, REF)
        assert closed is not None
        self.assertEqual(closed.exit_price, 19949.75)

    def test_short_position(self) -> None:
        self.broker.place_bracket(order(direction=Direction.SHORT, stop="20020", tp="19960"))
        self.assertEqual(self.broker.positions("acc")["NQ"].quantity, -2.0)
        self.broker.on_candle(bar("NQ", 19990, 19995, 19955, 19970, T0 + M5))
        closed = self.broker.closed_trade("acc", "NQ", T0, REF)
        assert closed is not None
        self.assertAlmostEqual(closed.realized_pnl, (19999.75 - 19960) * 20 * 2 - 8)

    def test_rejections(self) -> None:
        self.broker.place_bracket(order())
        with self.assertRaises(BrokerError):
            self.broker.place_bracket(order())  # one position per symbol
        with self.assertRaises(BrokerError):
            self.broker.place_bracket(OrderRequest("acc", BTC, Direction.LONG, Decimal("0.1"),
                                                   Decimal("59000"), None, "t2", 60000.0))  # no price
        with self.assertRaises(BrokerError):
            self.broker.account_snapshot("ghost")

    def test_state_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, StateStore(Path(tmp) / "s.db") as store:
            first = PaperBroker({"acc": 50_000.0}, store=store, clock=self.clock)
            first.set_price("NQ", 20000.0)
            first.on_candle(bar("NQ", 20000, 20001, 19999, 20000))
            first.place_bracket(order())
            second = PaperBroker({"acc": 50_000.0}, store=store, clock=self.clock)
            self.assertIn("NQ", second.positions("acc"))

    def test_bracket_prices_snap_conservatively(self) -> None:
        stop, tp = bracket_prices(NQ, Direction.LONG, 19980.1, 20040.4)
        self.assertEqual((stop, tp), (Decimal("19980.00"), Decimal("20040.25")))
        stop, tp = bracket_prices(NQ, Direction.SHORT, 20019.9, 19960.1)
        self.assertEqual((stop, tp), (Decimal("20020.00"), Decimal("19960.25")))


class FlakyBroker(Broker):
    """Wraps a paper broker; can be told to fail specific calls."""

    name = "flaky"

    def __init__(self, inner: PaperBroker) -> None:
        self.inner = inner
        self.fail_place: BrokerError | None = None
        self.fail_reads = False
        self.place_then_fail = False
        self.hide_closes = False

    def account_snapshot(self, account: str) -> AccountSnapshot:
        if self.fail_reads:
            raise BrokerError("connection refused", retryable=True)
        return self.inner.account_snapshot(account)

    def positions(self, account: str) -> dict[str, Position]:
        if self.fail_reads:
            raise BrokerError("connection refused", retryable=True)
        return self.inner.positions(account)

    def place_bracket(self, order: OrderRequest) -> OrderAck:
        if self.place_then_fail:
            self.inner.place_bracket(order)
            raise BrokerError("read timed out", retryable=True)
        if self.fail_place is not None:
            raise self.fail_place
        return self.inner.place_bracket(order)

    def close_position(self, account: str, symbol: str) -> None:
        self.inner.close_position(account, symbol)

    def closed_trade(self, account: str, symbol: str, since: datetime, trade: TradeRef) -> ClosedTrade | None:
        return None if self.hide_closes else self.inner.closed_trade(account, symbol, since, trade)


class ExecutionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name) / "state.db")
        self.clock = Clock()
        limits = RiskLimits(daily_loss_limit_pct=2.0, max_drawdown_pct=6.0, risk_per_trade_pct=1.0,
                            max_trades_per_day=10)
        balances = {"apex_1": 50_000.0, "apex_2": 100_000.0, "crypto_1": 100_000.0}
        self.manager = RiskManager({
            acc: RiskEngine(AccountConfig(acc, bal), limits, SessionConfig(), self.store, clock=self.clock)
            for acc, bal in balances.items()
        })
        self.events: list[RiskEvent] = []
        self.manager.subscribe(self.events.append)
        self.paper = PaperBroker(balances, clock=self.clock)
        self.flaky = FlakyBroker(self.paper)
        self.alerts: list[str] = []
        futures, crypto = frozenset({AssetClass.FUTURES}), frozenset({AssetClass.CRYPTO})
        self.executor = ExecutionEngine(
            self.manager,
            [AccountRoute("apex_1", "paper", "apex_1", futures),
             AccountRoute("apex_2", "flaky", "apex_2", futures),
             AccountRoute("crypto_1", "paper", "crypto_1", crypto)],
            {"paper": self.paper, "flaky": self.flaky},
            alert=self.alerts.append, clock=self.clock, max_signal_age=timedelta(minutes=10),
        )
        self.paper.on_candle(bar("NQ", 20000, 20002, 19998, 20000))
        self.paper.on_candle(bar("BTCUSDT", 60000, 60010, 59990, 60000))
        self.executor.reconcile()

    def tearDown(self) -> None:
        self.executor.close()
        self.store.close()
        self.tmp.cleanup()

    def signal(self, side: Side = Side.LONG, symbol: str = "NQ", price: float = 20000.0,
               stop: float | None = 19980.0, tp: float | None = 20040.0, **kw: Any) -> Signal:
        if side is Side.SHORT and stop is not None and stop < price:
            stop, tp = price + (price - stop), (price - (tp - price)) if tp else None
        return Signal("test", symbol, side, kw.get("time", T0), price,
                      stop=None if side is Side.FLAT else stop,
                      take_profit=None if side is Side.FLAT else tp)

    def results(self, signal: Signal) -> dict[str, ExecutionStatus]:
        return {r.account_id: r.status for r in self.executor.on_signal(signal)}


class ExecutionEngineTests(ExecutionFixture):
    def test_signal_goes_to_every_matching_account_sized_per_account(self) -> None:
        results = self.executor.on_signal(self.signal())
        self.assertEqual({r.account_id for r in results}, {"apex_1", "apex_2"})  # not crypto_1
        self.assertTrue(all(r.status is ExecutionStatus.FILLED for r in results))
        qty = {r.account_id: r.quantity for r in results}
        # 20-pt stop + fill slippage = 81 ticks * $5 + $4 = $409/contract.
        # apex_1 1% of $50k = $500 -> 1 contract; apex_2 $1,000 -> 2 contracts.
        self.assertEqual(qty, {"apex_1": Decimal("1"), "apex_2": Decimal("2")})
        opened = [e for e in self.events if isinstance(e, TradeOpenedEvent)]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0].stop_price, 19980.0)
        self.assertEqual(self.paper.positions("apex_2")["NQ"].quantity, 2.0)

    def test_crypto_signal_only_reaches_crypto_account(self) -> None:
        results = self.results(self.signal(symbol="BTCUSDT", price=60000.0, stop=59400.0, tp=61200.0))
        self.assertEqual(results, {"crypto_1": ExecutionStatus.FILLED})

    def test_risk_engine_veto_is_per_account(self) -> None:
        self.manager["apex_1"].halt("test")
        self.assertEqual(self.results(self.signal()),
                         {"apex_1": ExecutionStatus.REJECTED, "apex_2": ExecutionStatus.FILLED})

    def test_same_direction_is_skipped_and_opposite_reverses(self) -> None:
        self.executor.on_signal(self.signal())
        self.assertEqual(set(self.results(self.signal()).values()), {ExecutionStatus.SKIPPED})
        self.assertEqual(set(self.results(self.signal(Side.SHORT)).values()), {ExecutionStatus.FILLED})
        self.assertEqual(self.paper.positions("apex_1")["NQ"].quantity, -1.0)
        closes = [e for e in self.events if isinstance(e, TradeClosedEvent)]
        self.assertEqual({e.reason for e in closes}, {ExitReason.SIGNAL})

    def test_flat_signal_closes(self) -> None:
        self.executor.on_signal(self.signal())
        self.assertEqual(set(self.results(self.signal(Side.FLAT)).values()), {ExecutionStatus.CLOSED})
        self.assertEqual(self.paper.positions("apex_1"), {})
        self.assertEqual(set(self.results(self.signal(Side.FLAT)).values()), {ExecutionStatus.SKIPPED})

    def test_stop_out_is_detected_and_journaled(self) -> None:
        self.executor.on_signal(self.signal())
        self.paper.on_candle(bar("NQ", 20000, 20001, 19970, 19975, T0 + M5))
        self.executor.reconcile()
        closes = [e for e in self.events if isinstance(e, TradeClosedEvent)]
        self.assertEqual(len(closes), 2)
        self.assertEqual({e.reason for e in closes}, {ExitReason.STOP_LOSS})
        apex_1 = next(e for e in closes if e.account_id == "apex_1")
        self.assertAlmostEqual(apex_1.realized_pnl, (19979.75 - 20000.25) * 20 - 4)
        self.assertEqual(apex_1.balance, self.paper.account_snapshot("apex_1").balance)
        trades = self.store.recent_trades(10)
        self.assertEqual({t.exit_reason for t in trades}, {"sl"})
        self.assertEqual(self.manager["apex_1"].status().open_trades, ())

    def test_target_detected(self) -> None:
        self.executor.on_signal(self.signal())
        self.paper.on_candle(bar("NQ", 20000, 20045, 19999, 20040, T0 + M5))
        self.executor.reconcile()
        reasons = {e.reason for e in self.events if isinstance(e, TradeClosedEvent)}
        self.assertEqual(reasons, {ExitReason.TAKE_PROFIT})

    def test_halt_flattens_via_queue(self) -> None:
        self.executor.on_signal(self.signal())
        self.manager.on_halt(self.executor.on_halt)
        self.manager["apex_2"].halt("operator")  # e.g. from the dashboard thread
        self.assertIn("NQ", self.paper.positions("apex_2"))  # nothing done under the lock
        self.executor.process_requests()
        self.assertEqual(self.paper.positions("apex_2"), {})
        self.assertIn("NQ", self.paper.positions("apex_1"))
        close = next(e for e in self.events if isinstance(e, TradeClosedEvent))
        self.assertEqual(close.reason, ExitReason.MANUAL)

    def test_daily_loss_halt_flattens_with_daily_reason(self) -> None:
        self.manager.on_halt(self.executor.on_halt)
        self.executor.on_signal(self.signal())
        # 50 pts against: apex_1 (1 lot, $50k) and apex_2 (2 lots, $100k) both lose 2%.
        self.paper.set_price("NQ", 19950.0)
        self.executor.reconcile()
        self.executor.process_requests()
        closes = [e for e in self.events if isinstance(e, TradeClosedEvent)]
        self.assertEqual(sorted((e.account_id, e.reason) for e in closes),
                         [("apex_1", ExitReason.DAILY_HALT), ("apex_2", ExitReason.DAILY_HALT)])
        self.assertFalse(self.manager["apex_1"].check_new_trade().allowed)
        self.assertTrue(self.manager["crypto_1"].check_new_trade().allowed)

    def test_stale_signal_ignored(self) -> None:
        self.clock.now = T0 + timedelta(minutes=30)
        self.assertEqual(self.executor.on_signal(self.signal()), [])

    def test_broker_rejection_alerts(self) -> None:
        self.flaky.fail_place = BrokerError("insufficient margin")
        results = self.results(self.signal())
        self.assertEqual(results["apex_2"], ExecutionStatus.FAILED)
        self.assertEqual(results["apex_1"], ExecutionStatus.FILLED)
        self.assertTrue(any("insufficient margin" in a for a in self.alerts))

    def test_timed_out_order_that_filled_is_adopted(self) -> None:
        self.flaky.place_then_fail = True
        self.assertEqual(self.results(self.signal())["apex_2"], ExecutionStatus.FAILED)
        self.executor.reconcile()
        open_trades = self.manager["apex_2"].status().open_trades
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0].stop_price, 19980.0)
        self.assertTrue(any("timed out but filled" in a for a in self.alerts))

    def test_untracked_position_alerts_once(self) -> None:
        self.paper.place_bracket(order("apex_1"))
        self.executor.reconcile()
        self.executor.reconcile()
        self.assertEqual(sum("Untracked" in a for a in self.alerts), 1)

    def test_unreachable_broker_alerts_after_repeated_failures(self) -> None:
        self.flaky.fail_reads = True
        for _ in range(4):
            self.executor.reconcile()
        self.assertEqual(sum("unreachable" in a for a in self.alerts), 1)
        self.flaky.fail_reads = False
        self.executor.reconcile()
        self.assertTrue(any("restored" in a for a in self.alerts))

    def test_missing_close_details_recorded_after_grace(self) -> None:
        self.executor.on_signal(self.signal())
        self.flaky.hide_closes = True
        self.paper.close_position("apex_2", "NQ")
        self.executor.reconcile()
        self.assertEqual(len(self.manager["apex_2"].status().open_trades), 1)  # waiting
        self.clock.now = T0 + timedelta(minutes=3)
        self.executor.reconcile()
        self.assertEqual(self.manager["apex_2"].status().open_trades, ())
        self.assertTrue(any("P&amp;L is unavailable" in a for a in self.alerts))

    def test_unknown_route_broker(self) -> None:
        with self.assertRaises(ValueError):
            ExecutionEngine(self.manager, [AccountRoute("apex_1", "nope", "x")], {"paper": self.paper})


if __name__ == "__main__":
    unittest.main()
