"""Contract / lot size from stop-loss distance and a money-at-risk budget.

Sizing is done in :class:`~decimal.Decimal` and always rounds *against* the
trader: the stop distance is rounded up to whole ticks and the quantity is
rounded down to the instrument's step. A size that cannot meet the minimum
order quantity without exceeding the budget is rejected, never rounded up.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from enum import Enum


class AssetClass(str, Enum):
    FUTURES = "futures"
    CRYPTO = "crypto"


class PositionSizingError(ValueError):
    """The inputs cannot describe a valid trade (e.g. stop equals entry)."""


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    asset_class: AssetClass
    # Minimum price increment.
    tick_size: Decimal
    # Account-currency P&L of a one-tick move for one unit of ``qty_step`` = 1.
    tick_value: Decimal
    # Order quantity increment, minimum and maximum.
    qty_step: Decimal
    min_qty: Decimal
    max_qty: Decimal
    # Round-trip commission + fees per unit, counted as risk.
    fee_per_unit: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("tick_size", "tick_value", "qty_step", "min_qty", "max_qty"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{self.symbol}: {name} must be positive")
        if self.min_qty > self.max_qty:
            raise ValueError(f"{self.symbol}: min_qty exceeds max_qty")
        if self.fee_per_unit < 0:
            raise ValueError(f"{self.symbol}: fee_per_unit must not be negative")


D = Decimal

# Defaults; confirm against your broker / exchange contract specs.
INSTRUMENTS: dict[str, InstrumentSpec] = {
    # CME E-mini Nasdaq-100: 0.25 index points = $5.00.
    "NQ": InstrumentSpec("NQ", AssetClass.FUTURES, D("0.25"), D("5.00"), D("1"), D("1"), D("20"), D("4.00")),
    # CME Micro E-mini Nasdaq-100: 0.25 index points = $0.50.
    "MNQ": InstrumentSpec("MNQ", AssetClass.FUTURES, D("0.25"), D("0.50"), D("1"), D("1"), D("200"), D("1.00")),
    # Linear USDT perpetuals, quantity in coins: a 1-tick move on 1 coin = tick_size USDT.
    "BTCUSDT": InstrumentSpec("BTCUSDT", AssetClass.CRYPTO, D("0.1"), D("0.1"), D("0.001"), D("0.001"), D("100")),
    "ETHUSDT": InstrumentSpec("ETHUSDT", AssetClass.CRYPTO, D("0.01"), D("0.01"), D("0.01"), D("0.01"), D("1000")),
}


def get_instrument(symbol: str) -> InstrumentSpec:
    try:
        return INSTRUMENTS[symbol.upper()]
    except KeyError:
        raise PositionSizingError(f"unknown instrument {symbol!r}") from None


@dataclass(frozen=True)
class PositionSize:
    symbol: str
    quantity: Decimal
    stop_ticks: int
    risk_per_unit: Decimal
    # Money lost if the stop is hit, fees included.
    total_risk: Decimal
    risk_budget: Decimal
    rejected_reason: str | None = None

    @property
    def is_tradeable(self) -> bool:
        return self.rejected_reason is None and self.quantity > 0


def _to_decimal(name: str, value: float | Decimal | str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        raise PositionSizingError(f"{name}={value!r} is not a number") from None
    if not result.is_finite():
        raise PositionSizingError(f"{name}={value!r} is not finite")
    return result


def calculate_position_size(
    instrument: InstrumentSpec,
    entry_price: float | Decimal,
    stop_price: float | Decimal,
    risk_budget: float | Decimal,
) -> PositionSize:
    """Largest quantity whose loss at ``stop_price`` stays within ``risk_budget``."""
    entry = _to_decimal("entry_price", entry_price)
    stop = _to_decimal("stop_price", stop_price)
    budget = _to_decimal("risk_budget", risk_budget)
    if entry <= 0 or stop <= 0:
        raise PositionSizingError("entry and stop prices must be positive")
    if entry == stop:
        raise PositionSizingError("stop_price equals entry_price; the risk is undefined")

    stop_ticks = int(((entry - stop).copy_abs() / instrument.tick_size).to_integral_value(ROUND_CEILING))
    risk_per_unit = stop_ticks * instrument.tick_value + instrument.fee_per_unit

    def result(qty: Decimal, reason: str | None = None) -> PositionSize:
        return PositionSize(
            symbol=instrument.symbol,
            quantity=qty,
            stop_ticks=stop_ticks,
            risk_per_unit=risk_per_unit,
            total_risk=qty * risk_per_unit,
            risk_budget=budget,
            rejected_reason=reason,
        )

    if budget <= 0:
        return result(D("0"), "no risk budget available")

    steps = (budget / risk_per_unit / instrument.qty_step).to_integral_value(ROUND_FLOOR)
    qty = min(steps * instrument.qty_step, instrument.max_qty)
    # Cap at max_qty may leave a value off-step if max_qty is; re-floor.
    qty = (qty / instrument.qty_step).to_integral_value(ROUND_FLOOR) * instrument.qty_step

    if qty < instrument.min_qty:
        min_risk = instrument.min_qty * risk_per_unit
        return result(
            D("0"),
            f"minimum size {instrument.min_qty} risks {min_risk:.2f}, above budget {budget:.2f}; "
            "tighten the stop or skip the trade",
        )
    return result(qty)
