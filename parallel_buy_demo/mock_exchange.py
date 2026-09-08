"""A simulated spot exchange, good enough to show what a real one would do.

Nothing here touches the network. There are no API keys, no proxies and no
money. The point is the matching engine: a real exchange has *one* order book
per symbol and matches arrivals one at a time, so a hundred coroutines firing
"simultaneously" still queue up and eat each other's liquidity.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field


class OrderRejected(Exception):
    """The exchange refused the order (bad size, notional, or no liquidity)."""


@dataclass
class Fill:
    price: float
    amount: float


@dataclass
class Order:
    id: str
    account: str
    side: str
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled_base(self) -> float:
        return sum(f.amount for f in self.fills)

    @property
    def cost_quote(self) -> float:
        return sum(f.price * f.amount for f in self.fills)

    @property
    def average(self) -> float:
        return self.cost_quote / self.filled_base if self.filled_base else 0.0


class MockExchange:
    """One symbol, one ask ladder, one serial matching engine.

    The ladder is the whole story. ``level_size`` BTC sits at every ``tick``
    dollars above ``start_price``; sweeping it is what slippage *is*.
    """

    # Binance's real BTC/USDT limits, near enough for the demo.
    MIN_NOTIONAL = 5.0
    MAX_BASE_PER_ORDER = 9_000.0

    def __init__(
        self,
        start_price: float = 65_000.0,
        tick: float = 1.5,
        level_size: float = 0.35,
        levels: int = 40_000,
        seed: int = 7,
    ) -> None:
        self.start_price = start_price
        self.tick = tick
        self.level_size = level_size
        self._rng = random.Random(seed)
        # asks[i] = remaining size at start_price + i * tick
        self._asks = [level_size] * levels
        self._cursor = 0  # first level with liquidity left
        self._lock = asyncio.Lock()  # the matching engine is serial. Always.
        self._seq = 0
        self.tape: list[Order] = []

    # -- market data ----------------------------------------------------

    @property
    def best_ask(self) -> float:
        return self.start_price + self._cursor * self.tick

    def depth_within(self, pct: float) -> float:
        """BTC available within `pct` of the current best ask."""
        limit = self.best_ask * (1 + pct / 100)
        total = 0.0
        for i in range(self._cursor, len(self._asks)):
            if self.start_price + i * self.tick > limit:
                break
            total += self._asks[i]
        return total

    def replenish(self, fraction: float = 0.6) -> None:
        """Market makers come back. Called between TWAP slices."""
        recovered = int(self._cursor * fraction)
        for i in range(self._cursor - recovered, self._cursor):
            self._asks[i] = self.level_size
        self._cursor -= recovered

    # -- order entry ----------------------------------------------------

    async def create_market_buy_order(
        self,
        symbol: str,
        amount: float | None = None,
        params: dict | None = None,
    ) -> Order:
        """ccxt signature. `amount` is in BASE currency (BTC), not dollars.

        Pass ``params={'quoteOrderQty': usd}`` to spend a dollar amount, which
        is what almost everyone actually means.
        """
        params = params or {}
        quote_qty = params.get("quoteOrderQty")
        account = params.get("_account", "anon")

        if (amount is None) == (quote_qty is None):
            raise OrderRejected("pass exactly one of amount (BTC) or quoteOrderQty (USDT)")

        if amount is not None and amount > self.MAX_BASE_PER_ORDER:
            raise OrderRejected(
                f"amount {amount:,.0f} BTC exceeds max order size "
                f"{self.MAX_BASE_PER_ORDER:,.0f} BTC (filter MARKET_LOT_SIZE)"
            )
        if quote_qty is not None and quote_qty < self.MIN_NOTIONAL:
            raise OrderRejected(f"notional {quote_qty} below MIN_NOTIONAL {self.MIN_NOTIONAL}")

        # Network + gateway latency, so arrival order is not call order.
        await asyncio.sleep(self._rng.uniform(0.010, 0.090))

        async with self._lock:  # <- every parallel order lines up right here
            return self._match(account, amount, quote_qty)

    def _match(self, account: str, base_qty: float | None, quote_qty: float | None) -> Order:
        self._seq += 1
        order = Order(id=f"{self._seq:06d}", account=account, side="buy")

        base_left = base_qty if base_qty is not None else float("inf")
        quote_left = quote_qty if quote_qty is not None else float("inf")

        while self._cursor < len(self._asks) and base_left > 1e-12 and quote_left > 1e-8:
            price = self.start_price + self._cursor * self.tick
            available = self._asks[self._cursor]
            take = min(available, base_left, quote_left / price)
            if take <= 1e-12:
                break
            self._asks[self._cursor] -= take
            if self._asks[self._cursor] <= 1e-12:
                self._cursor += 1
            base_left -= take
            quote_left -= take * price
            order.fills.append(Fill(price=price, amount=take))

        if not order.fills:
            raise OrderRejected("no liquidity — book is empty")
        self.tape.append(order)
        return order

    async def close(self) -> None:  # ccxt parity
        return None
