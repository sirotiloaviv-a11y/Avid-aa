"""Stop loss, take profit, position sizing and the liquidity guard.

The sizing rule is fixed-fractional: the position is sized so that a fill at
the reference entry followed by the stop being hit loses exactly
``ACCOUNT_EQUITY * RISK_PER_TRADE_PCT / 100``::

    units = risk_budget / (|entry - stop| + fee_rate * (entry + stop))

With ``FEE_RATE_PCT=0`` (the default) that is simply
``risk_budget / |entry - stop|``. Three things can only make the realised
risk *smaller*, never larger, and the plan reports each:

* rounding the quantity down to the exchange's lot step,
* the leverage cap (``MAX_LEVERAGE``) on very tight stops, and
* the liquidity guard in ``reduce`` mode.

The entry zone lies on the favourable side of the reference price only (at or
below it for a long, at or above it for a short), so any fill inside the zone
keeps the loss at the stop within budget.

Liquidity guard
---------------
A market order walks the book, so its average price is worse than the mid
price. :func:`check_liquidity` simulates that fill against a live order book
snapshot and reports the expected slippage vs mid (half the spread included,
since you pay it). If that exceeds ``MAX_SLIPPAGE_PCT`` the plan is warned,
reduced to the largest size that stays within the threshold, or filtered —
see ``LIQUIDITY_ACTION``.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .config import LiquiditySettings, RiskSettings
from .market_data import OrderBook
from .strategy import Direction, Signal

log = logging.getLogger(__name__)

AmountRounder = Callable[[float], float]


class RiskError(ValueError):
    """The signal cannot be turned into a valid trade plan."""


# ------------------------------------------------------------------ liquidity


@dataclass(frozen=True)
class LiquidityCheck:
    side: str  # "buy" (a long's entry) or "sell" (a short's entry)
    units: float  # size that was checked
    filled_units: float  # how much of it the fetched depth could absorb
    avg_fill_price: Optional[float]  # average price of the filled part
    mid_price: float
    spread_pct: float
    slippage_pct: float  # adverse move of the average fill vs mid, in percent
    max_units_within_threshold: float  # largest size whose slippage stays within the threshold
    threshold_pct: float

    @property
    def fully_filled(self) -> bool:
        return self.filled_units >= self.units * (1 - 1e-9)

    @property
    def ok(self) -> bool:
        return self.fully_filled and self.slippage_pct <= self.threshold_pct


def simulate_fill(levels: Sequence[tuple[float, float]], units: float) -> tuple[float, Optional[float]]:
    """Walk book levels (best first) with a market order for ``units``.

    Returns ``(filled_units, average_price)``; the average is None if nothing filled.
    """
    remaining, cost, filled = units, 0.0, 0.0
    for price, amount in levels:
        if remaining <= 0:
            break
        take = min(amount, remaining)
        cost += take * price
        filled += take
        remaining -= take
    return filled, (cost / filled if filled > 0 else None)


def max_units_within(levels: Sequence[tuple[float, float]], limit_price: float, buying: bool) -> float:
    """Largest market-order size whose *average* fill stays at ``limit_price`` or better.

    Levels whose price is at or better than the limit are taken whole. At the
    first level beyond it, solving ``(cost + p*q) / (units + q) = limit`` gives
    the partial quantity ``q = (limit*units - cost) / (p - limit)``; the same
    formula holds for buys (asks ascending) and sells (bids descending).
    """
    units = cost = 0.0
    for price, amount in levels:
        within = price <= limit_price if buying else price >= limit_price
        if within:
            units += amount
            cost += price * amount
            continue
        q = (limit_price * units - cost) / (price - limit_price)
        if q >= amount:  # the whole level still keeps the average within the limit
            units += amount
            cost += price * amount
            continue
        return units + max(q, 0.0)
    return units  # depth exhausted: a lower bound on what the full book could absorb


def check_liquidity(
    book: OrderBook, direction: Direction, units: float, max_slippage_pct: float
) -> LiquidityCheck:
    """Expected slippage of entering ``units`` with a market order right now."""
    mid = book.mid
    if mid is None:
        raise RiskError(f"order book for {book.symbol} is empty on one side")
    buying = direction is Direction.LONG
    levels = book.asks if buying else book.bids
    filled, avg = simulate_fill(levels, units)
    if avg is None:
        slippage = float("inf")
    else:
        slippage = ((avg - mid) if buying else (mid - avg)) / mid * 100.0
    threshold = max_slippage_pct / 100.0
    limit_price = mid * (1 + threshold) if buying else mid * (1 - threshold)
    return LiquidityCheck(
        side="buy" if buying else "sell",
        units=units,
        filled_units=filled,
        avg_fill_price=avg,
        mid_price=mid,
        spread_pct=(book.asks[0][0] - book.bids[0][0]) / mid * 100.0,
        slippage_pct=slippage,
        max_units_within_threshold=max_units_within(levels, limit_price, buying),
        threshold_pct=max_slippage_pct,
    )


# ----------------------------------------------------------------------- plan


@dataclass(frozen=True)
class TradePlan:
    signal: Signal
    entry: float  # reference entry the position is sized from
    entry_zone: tuple[float, float]  # (low, high)
    stop_loss: float
    stop_method: str  # human-readable: "swing low − 0.2 ATR", "1.5 ATR", ...
    take_profit: float
    risk_reward_ratio: float
    units: float
    notional: float
    risk_budget: float  # equity * risk %
    risk_amount: float  # loss at the stop for the final (rounded, capped) size, incl. fees
    reward_amount: float  # profit at the take profit, net of fees
    leverage: float  # notional / equity
    capped_by_leverage: bool
    account_equity: float
    fee_rate: float = 0.0  # per side, as a fraction
    # Liquidity guard results (None when the check is off or the book was unavailable).
    liquidity: Optional[LiquidityCheck] = None
    liquidity_error: Optional[str] = None
    # "ok" | "warned" | "reduced" | "filtered" | "unchecked"
    liquidity_action: str = "unchecked"
    original_units: Optional[float] = None  # set when the guard reduced the size

    @property
    def direction(self) -> Direction:
        return self.signal.direction

    @property
    def symbol(self) -> str:
        return self.signal.symbol

    @property
    def stop_loss_pct(self) -> float:
        """Signed percentage move from entry to stop (negative for a long)."""
        return (self.stop_loss - self.entry) / self.entry * 100.0

    @property
    def take_profit_pct(self) -> float:
        """Signed percentage move from entry to target (positive for a long)."""
        return (self.take_profit - self.entry) / self.entry * 100.0

    @property
    def risk_pct_of_equity(self) -> float:
        return self.risk_amount / self.account_equity * 100.0

    @property
    def risk_with_slippage(self) -> Optional[float]:
        """Loss at the stop if entered by market order at the simulated average fill."""
        liq = self.liquidity
        if liq is None or liq.avg_fill_price is None or not liq.fully_filled:
            return None
        fill = liq.avg_fill_price
        return self.units * (abs(fill - self.stop_loss) + self.fee_rate * (fill + self.stop_loss))


class RiskManager:
    def __init__(self, settings: RiskSettings) -> None:
        self.settings = settings

    @property
    def risk_budget(self) -> float:
        return self.settings.risk_budget

    def update_account(
        self, account_equity: Optional[float] = None, risk_per_trade_pct: Optional[float] = None
    ) -> RiskSettings:
        """Change equity and/or risk % at runtime (e.g. from the dashboard).

        Applies to the next plan built. The same bounds as the .env settings
        are enforced; changes are not written back to .env.
        """
        equity = self.settings.account_equity if account_equity is None else float(account_equity)
        risk_pct = self.settings.risk_per_trade_pct if risk_per_trade_pct is None else float(risk_per_trade_pct)
        if not equity > 0 or equity != equity or equity == float("inf"):
            raise RiskError("ACCOUNT_EQUITY must be a positive number")
        if not 0 < risk_pct <= 5:
            raise RiskError("RISK_PER_TRADE_PCT must be > 0 and <= 5 (it is a percentage)")
        self.settings = dataclasses.replace(
            self.settings, account_equity=equity, risk_per_trade_pct=risk_pct
        )
        return self.settings

    # ------------------------------------------------------------------ stops

    def stop_loss(
        self,
        direction: Direction,
        entry: float,
        atr: float,
        swing_level: Optional[float] = None,
    ) -> tuple[float, str]:
        """Return ``(stop_price, method)`` according to ``STOP_MODE``.

        * ``atr``    — entry ∓ ATR_STOP_MULTIPLIER × ATR.
        * ``swing``  — beyond the swing level by SWING_BUFFER_ATR × ATR; falls
          back to the ATR stop when there is no usable swing level.
        * ``hybrid`` — the swing stop, but widened to MIN_STOP_ATR when it
          sits inside normal noise, and replaced by the ATR stop when it is
          further than MAX_STOP_ATR away (a far stop means a tiny position
          and a target that will rarely be reached).
        """
        if entry <= 0 or atr <= 0:
            raise RiskError(f"entry ({entry}) and ATR ({atr}) must be positive")
        s = self.settings
        sign = -1.0 if direction is Direction.LONG else 1.0  # stop is below a long, above a short
        side = "low" if direction is Direction.LONG else "high"

        atr_stop = entry + sign * s.atr_stop_multiplier * atr
        atr_method = f"{s.atr_stop_multiplier:g} ATR"

        swing_usable = swing_level is not None and (
            swing_level < entry if direction is Direction.LONG else swing_level > entry
        )
        if s.stop_mode == "atr" or not swing_usable:
            stop, method = atr_stop, atr_method
        else:
            assert swing_level is not None
            stop = swing_level + sign * s.swing_buffer_atr * atr
            method = f"swing {side} {'−' if sign < 0 else '+'} {s.swing_buffer_atr:g} ATR"
            if s.stop_mode == "hybrid":
                distance_atr = abs(entry - stop) / atr
                if distance_atr < s.min_stop_atr:
                    stop = entry + sign * s.min_stop_atr * atr
                    method = f"swing {side} widened to {s.min_stop_atr:g} ATR"
                elif distance_atr > s.max_stop_atr:
                    stop, method = atr_stop, f"{atr_method} (swing {side} too far)"

        if stop <= 0:
            raise RiskError(f"stop loss {stop:.8g} is not a valid price")
        return stop, method

    def take_profit(self, direction: Direction, entry: float, stop: float) -> float:
        distance = abs(entry - stop)
        sign = 1.0 if direction is Direction.LONG else -1.0
        target = entry + sign * self.settings.risk_reward_ratio * distance
        if target <= 0:
            raise RiskError(f"take profit {target:.8g} is not a valid price")
        return target

    # ----------------------------------------------------------------- sizing

    def loss_per_unit(self, entry: float, stop: float) -> float:
        """Loss for one unit if filled at ``entry`` and stopped at ``stop``, including fees."""
        fee_rate = self.settings.fee_rate_pct / 100.0
        return abs(entry - stop) + fee_rate * (entry + stop)

    def position_size(
        self,
        entry: float,
        stop: float,
        amount_rounder: Optional[AmountRounder] = None,
    ) -> tuple[float, bool]:
        """Return ``(units, capped_by_leverage)`` sized to the risk budget.

        ``amount_rounder`` should round *down* to the exchange lot step
        (see ``MarketDataFeed.round_amount``).
        """
        if entry <= 0 or stop <= 0 or entry == stop:
            raise RiskError(f"invalid entry/stop pair: {entry} / {stop}")
        units = self.risk_budget / self.loss_per_unit(entry, stop)
        max_units = self.settings.account_equity * self.settings.max_leverage / entry
        capped = units > max_units
        if capped:
            units = max_units
        if amount_rounder is not None:
            units = min(units, amount_rounder(units))
        if units <= 0:
            raise RiskError("position size rounds to zero at the exchange's lot step")
        return units, capped

    # ------------------------------------------------------------------- plan

    def build_plan(self, signal: Signal, amount_rounder: Optional[AmountRounder] = None) -> TradePlan:
        """Turn a signal into a complete, sized trade plan."""
        s = self.settings
        direction, entry, atr = signal.direction, signal.entry_price, signal.atr
        stop, method = self.stop_loss(direction, entry, atr, signal.invalidation_level)
        target = self.take_profit(direction, entry, stop)
        units, capped = self.position_size(entry, stop, amount_rounder)

        # Entry zone: from the reference price toward the stop, never past the
        # halfway point to it (a fill that deep would distort the R:R).
        zone_depth = min(s.entry_zone_atr * atr, 0.5 * abs(entry - stop))
        if direction is Direction.LONG:
            zone = (entry - zone_depth, entry)
        else:
            zone = (entry, entry + zone_depth)

        plan = TradePlan(
            signal=signal,
            entry=entry,
            entry_zone=zone,
            stop_loss=stop,
            stop_method=method,
            take_profit=target,
            risk_reward_ratio=s.risk_reward_ratio,
            units=0.0,
            notional=0.0,
            risk_budget=self.risk_budget,
            risk_amount=0.0,
            reward_amount=0.0,
            leverage=0.0,
            capped_by_leverage=capped,
            account_equity=s.account_equity,
            fee_rate=s.fee_rate_pct / 100.0,
        )
        return self._with_units(plan, units)

    def _with_units(self, plan: TradePlan, units: float) -> TradePlan:
        """Recompute every size-derived field of ``plan`` for ``units``."""
        entry, fee = plan.entry, plan.fee_rate
        notional = units * entry
        return dataclasses.replace(
            plan,
            units=units,
            notional=notional,
            risk_amount=units * (abs(entry - plan.stop_loss) + fee * (entry + plan.stop_loss)),
            reward_amount=units * (abs(plan.take_profit - entry) - fee * (entry + plan.take_profit)),
            leverage=notional / plan.account_equity,
        )

    def apply_liquidity(
        self,
        plan: TradePlan,
        book: OrderBook,
        settings: LiquiditySettings,
        amount_rounder: Optional[AmountRounder] = None,
    ) -> TradePlan:
        """Check ``plan`` against ``book`` and apply ``LIQUIDITY_ACTION``.

        The returned plan's ``liquidity_action`` says what happened; a
        ``"filtered"`` plan should not be sent.
        """
        check = check_liquidity(book, plan.direction, plan.units, settings.max_slippage_pct)
        if check.ok:
            return dataclasses.replace(plan, liquidity=check, liquidity_action="ok")
        if settings.action == "warn":
            return dataclasses.replace(plan, liquidity=check, liquidity_action="warned")
        if settings.action == "filter":
            return dataclasses.replace(plan, liquidity=check, liquidity_action="filtered")

        # reduce: the largest size the book absorbs within the threshold.
        units = min(plan.units, check.max_units_within_threshold)
        if amount_rounder is not None and units > 0:
            units = min(units, amount_rounder(units))
        if units <= 0:
            return dataclasses.replace(plan, liquidity=check, liquidity_action="filtered")
        reduced = self._with_units(plan, units)
        recheck = check_liquidity(book, plan.direction, units, settings.max_slippage_pct)
        return dataclasses.replace(
            reduced, liquidity=recheck, liquidity_action="reduced", original_units=plan.units
        )
