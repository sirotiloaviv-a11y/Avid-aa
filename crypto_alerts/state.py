"""In-memory runtime state: what the dashboard shows.

The feed reports connection health and live prices (it calls the
``FeedListener`` methods), the engine records evaluations and alerts, and the
dashboard renders :meth:`RuntimeState.snapshot`. Everything runs on one event
loop, so no locking is needed. Nothing here is persisted; a restart starts a
fresh log.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from .config import Settings
from .market_data import Candle
from .risk_manager import TradePlan

DAY_MS = 86_400_000


@dataclass
class SymbolStatus:
    symbol: str
    feed_state: str = "pending"  # pending | connecting | live | reconnecting | stopped
    last_error: Optional[str] = None
    reconnects: int = 0
    price: Optional[float] = None
    updated_ms: Optional[int] = None  # when the last price arrived (local clock)
    last_closed_ms: Optional[int] = None  # open time of the last evaluated candle
    rsi: Optional[float] = None
    volume_ratio: Optional[float] = None
    atr: Optional[float] = None
    signals: int = 0


@dataclass
class AlertRecord:
    time_ms: int
    symbol: str
    direction: str
    # sent | filtered (liquidity) | suppressed (cooldown) | discarded (risk error)
    status: str
    urgent: bool = False
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    units: Optional[float] = None
    notional: Optional[float] = None
    risk_amount: Optional[float] = None
    summary: str = ""
    conviction: list[str] = field(default_factory=list)
    liquidity: Optional[str] = None  # ok | warned | reduced | filtered | unchecked
    slippage_pct: Optional[float] = None
    note: str = ""


class RuntimeState:
    def __init__(
        self,
        symbols: tuple[str, ...] | list[str] = (),
        max_alerts: int = 200,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self.started_ms = self._now()
        self.symbols: dict[str, SymbolStatus] = {s: SymbolStatus(s) for s in symbols}
        self.alerts: deque[AlertRecord] = deque(maxlen=max_alerts)
        self.risk_changes: deque[dict[str, Any]] = deque(maxlen=50)

    def _now(self) -> int:
        return int(self._clock() * 1000)

    def _status(self, symbol: str) -> SymbolStatus:
        return self.symbols.setdefault(symbol, SymbolStatus(symbol))

    # ---------------------------------------------------------- FeedListener

    def on_feed_state(self, symbol: str, state: str, error: Optional[str] = None) -> None:
        status = self._status(symbol)
        if state == "reconnecting":
            status.reconnects += 1
        status.feed_state = state
        if error is not None:
            status.last_error = error

    def on_tick(self, symbol: str, candle: Candle) -> None:
        status = self._status(symbol)
        status.price = candle.close
        status.updated_ms = self._now()

    # ---------------------------------------------------------------- engine

    def record_evaluation(
        self, symbol: str, candle: Candle, rsi: Optional[float], volume_ratio: Optional[float], atr: Optional[float]
    ) -> None:
        status = self._status(symbol)
        status.last_closed_ms = candle.timestamp
        status.rsi, status.volume_ratio, status.atr = rsi, volume_ratio, atr

    def record_alert(self, plan: Optional[TradePlan], *, symbol: str, direction: str, status: str,
                     urgent: bool = False, note: str = "") -> AlertRecord:
        record = AlertRecord(time_ms=self._now(), symbol=symbol, direction=direction, status=status,
                             urgent=urgent, note=note)
        if plan is not None:
            record.entry = plan.entry
            record.stop_loss = plan.stop_loss
            record.take_profit = plan.take_profit
            record.units = plan.units
            record.notional = plan.notional
            record.risk_amount = plan.risk_amount
            record.summary = plan.signal.summary
            record.conviction = list(plan.signal.conviction_factors)
            record.liquidity = plan.liquidity_action
            if plan.liquidity is not None and plan.liquidity.fully_filled:
                record.slippage_pct = plan.liquidity.slippage_pct
        if status == "sent":
            self._status(symbol).signals += 1
        self.alerts.appendleft(record)
        return record

    def record_risk_change(self, old: dict[str, float], new: dict[str, float], source: str) -> None:
        self.risk_changes.appendleft({"time_ms": self._now(), "old": old, "new": new, "source": source})

    # -------------------------------------------------------------- snapshot

    def snapshot(self, settings: Settings, risk_settings: Any, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """JSON-ready view of everything the dashboard shows."""
        now = self._now()
        recent = [a for a in self.alerts if now - a.time_ms <= DAY_MS]
        sent = [a for a in recent if a.status == "sent"]
        liq = settings.liquidity
        return {
            "now_ms": now,
            "started_ms": self.started_ms,
            "exchange": settings.exchange.exchange_id,
            "timeframe": settings.exchange.timeframe,
            "symbols": [asdict(s) for s in self.symbols.values()],
            "alerts": [asdict(a) for a in self.alerts],
            "risk": {
                "account_equity": risk_settings.account_equity,
                "risk_per_trade_pct": risk_settings.risk_per_trade_pct,
                "risk_budget": risk_settings.risk_budget,
                "risk_reward_ratio": risk_settings.risk_reward_ratio,
                "stop_mode": risk_settings.stop_mode,
                "max_leverage": risk_settings.max_leverage,
                "fee_rate_pct": risk_settings.fee_rate_pct,
                "liquidity_check": liq.enabled,
                "liquidity_action": liq.action,
                "max_slippage_pct": liq.max_slippage_pct,
            },
            "last_24h": {
                "alerts_sent": len(sent),
                "urgent": sum(1 for a in sent if a.urgent),
                "filtered": sum(1 for a in recent if a.status == "filtered"),
                "suppressed": sum(1 for a in recent if a.status == "suppressed"),
                # If every alert were taken and stopped out: the worst case of following them all.
                "risk_if_all_stopped": sum(a.risk_amount or 0.0 for a in sent),
            },
            "risk_changes": list(self.risk_changes),
            **(extra or {}),
        }
