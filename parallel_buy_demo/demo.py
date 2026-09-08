"""Three ways to spend $10,000,000 on BTC, run against a simulated exchange.

    python -m parallel_buy_demo.demo

Scenario A is the script as originally written, B is the same idea with the
size bug fixed, C is what a desk would actually do. Nothing here connects to
anything; there is no live-trading path in this file to switch on.
"""

from __future__ import annotations

import asyncio
import time

from .mock_exchange import MockExchange, Order, OrderRejected

SYMBOL = "BTC/USDT"
ACCOUNTS = 100
BUDGET_PER_ACCOUNT = 100_000.0
TOTAL_BUDGET = ACCOUNTS * BUDGET_PER_ACCOUNT


def report(title: str, exchange: MockExchange, orders: list[Order], errors: list[str],
           started_at: float, elapsed: float) -> None:
    filled = sum(o.filled_base for o in orders)
    spent = sum(o.cost_quote for o in orders)
    print(f"\n{title}")
    print("-" * len(title))
    if errors:
        shown = errors[0]
        print(f"  rejected      {len(errors)}/{len(errors) + len(orders)} orders")
        print(f"  first error   {shown}")
    if not orders:
        print("  nothing filled.\n")
        return
    avg = spent / filled
    slip = (avg / started_at - 1) * 100
    ideal = spent / started_at
    print(f"  orders filled {len(orders)}")
    print(f"  BTC acquired  {filled:,.4f}")
    print(f"  USDT spent    ${spent:,.0f}")
    print(f"  start ask     ${started_at:,.2f}")
    print(f"  avg fill      ${avg:,.2f}")
    print(f"  final ask     ${exchange.best_ask:,.2f}  ({(exchange.best_ask/started_at-1)*100:+.2f}%)")
    print(f"  slippage      {slip:+.3f}%  =  ${spent - filled*started_at:,.0f} burned")
    print(f"  vs. no impact you would have got {ideal - filled:+,.4f} BTC more")
    print(f"  wall clock    {elapsed:.2f}s")


async def scenario_a_as_written() -> None:
    """The original: create_market_buy_order(symbol, 100000).

    ccxt reads that second positional argument as BASE currency, so this asks
    for 100,000 BTC per account — about $6.5bn each, $650bn in total.
    """
    ex = MockExchange()
    start = ex.best_ask
    orders: list[Order] = []
    errors: list[str] = []

    async def buy(i: int) -> None:
        try:
            o = await ex.create_market_buy_order(
                SYMBOL, BUDGET_PER_ACCOUNT, params={"_account": f"acct{i:03d}"}
            )
            orders.append(o)
        except OrderRejected as e:
            errors.append(str(e))

    t0 = time.perf_counter()
    await asyncio.gather(*(buy(i) for i in range(ACCOUNTS)))
    report("A — as written: amount=100000 treated as BTC",
           ex, orders, errors, start, time.perf_counter() - t0)


async def scenario_b_parallel_market() -> None:
    """Size bug fixed: quoteOrderQty=$100k, still all 100 fired at once."""
    ex = MockExchange()
    start = ex.best_ask
    orders: list[Order] = []
    errors: list[str] = []

    async def buy(i: int) -> None:
        try:
            o = await ex.create_market_buy_order(
                SYMBOL,
                params={"quoteOrderQty": BUDGET_PER_ACCOUNT, "_account": f"acct{i:03d}"},
            )
            orders.append(o)
        except OrderRejected as e:
            errors.append(str(e))

    t0 = time.perf_counter()
    await asyncio.gather(*(buy(i) for i in range(ACCOUNTS)))
    report("B — fixed size, 100 market orders in parallel",
           ex, orders, errors, start, time.perf_counter() - t0)


async def scenario_c_twap(slices: int = 100, pause: float = 0.02) -> None:
    """One account, the same $10m, sliced over time so the book can recover."""
    ex = MockExchange()
    start = ex.best_ask
    orders: list[Order] = []
    errors: list[str] = []
    per_slice = TOTAL_BUDGET / slices

    t0 = time.perf_counter()
    for i in range(slices):
        try:
            orders.append(await ex.create_market_buy_order(
                SYMBOL, params={"quoteOrderQty": per_slice, "_account": "acct000"}
            ))
        except OrderRejected as e:
            errors.append(str(e))
        await asyncio.sleep(pause)
        ex.replenish()  # makers refill the ladder between slices
    report(f"C — one account, TWAP over {slices} slices",
           ex, orders, errors, start, time.perf_counter() - t0)


async def main() -> None:
    ref = MockExchange()
    print(f"simulated {SYMBOL} book: best ask ${ref.best_ask:,.2f}, "
          f"{ref.depth_within(0.1):.2f} BTC within 0.1%")
    print(f"target: ${TOTAL_BUDGET:,.0f} of BTC\n")
    await scenario_a_as_written()
    await scenario_b_parallel_market()
    await scenario_c_twap()
    print("\nParallel does not mean simultaneous: the exchange has one book and")
    print("matches arrivals one at a time, so the 100 orders queue up and each")
    print("one pays for the impact of the ones before it.\n")


if __name__ == "__main__":
    asyncio.run(main())
