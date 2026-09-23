"""Stop loss, take profit and position sizing.

The sizing rule is fixed-fractional: the position is sized so that a fill at
the reference entry followed by the stop being hit loses exactly
``ACCOUNT_EQUITY * RISK_PER_TRADE_PCT / 100``::

    units = risk_budget / (|entry - stop| + fee_rate * (entry + stop))

With ``FEE_RATE_PCT=0`` (the default) that is simply
``risk_budget / |entry - stop|``. Two things can only make the realised risk
*smaller*, never larger, and the plan reports both:

* rounding the quantity down to the exchange's lot step, and
* the leverage cap (``MAX_LEVERAGE``) on very tight stops.

The entry zone lies on the favourable side of the reference price only (at or
below it for a long, at or above it for a short), so any fill inside the zone
keeps the loss at the stop within budget. Slippage beyond the zone is not
covered — that is what "don't chase" in the alert is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .config import RiskSettings
from .strategy import Direction, Signal

AmountRounder = Callable[[float], float]


class RiskError(ValueError):
    """The signal cannot be turned into a valid trade plan."""


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


class RiskManager:
    def __init__(self, settings: RiskSettings) -> None:
        self.settings = settings

    @property
    def risk_budget(self) -> float:
        return self.settings.risk_budget

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

        fee_rate = s.fee_rate_pct / 100.0
        notional = units * entry
        return TradePlan(
            signal=signal,
            entry=entry,
            entry_zone=zone,
            stop_loss=stop,
            stop_method=method,
            take_profit=target,
            risk_reward_ratio=s.risk_reward_ratio,
            units=units,
            notional=notional,
            risk_budget=self.risk_budget,
            risk_amount=units * self.loss_per_unit(entry, stop),
            reward_amount=units * (abs(target - entry) - fee_rate * (entry + target)),
            leverage=notional / s.account_equity,
            capped_by_leverage=capped,
            account_equity=s.account_equity,
        )
