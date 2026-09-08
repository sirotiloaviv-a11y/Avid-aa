# parallel_buy_demo

A simulation of buying $10,000,000 of BTC across many accounts at once.

```bash
python -m parallel_buy_demo.demo
```

No network, no API keys, no proxies, no money. `mock_exchange.py` is a local
order book with a serial matching engine; there is no live-trading code path in
here to enable.

## What it shows

Three ways to spend the same $10m:

| | approach | avg fill | slippage |
|---|---|---|---|
| A | `create_market_buy_order(symbol, 100000)` × 100, in parallel | — | rejected |
| B | `quoteOrderQty=$100k` × 100, in parallel | $65,327 | +0.50% (**$50k**) |
| C | one account, TWAP over 100 slices | $65,009 | +0.01% ($1.3k) |

### A — the size argument is BTC, not dollars

ccxt's `create_market_buy_order(symbol, amount)` takes `amount` in the **base**
currency. Passing `100000` meaning "a hundred thousand dollars" actually asks
for 100,000 BTC — roughly $6.5bn per account. Binance rejects it on the
`MARKET_LOT_SIZE` filter, which is the good outcome; on a venue with looser
filters and a funded account it is not. To spend a dollar amount, pass
`params={'quoteOrderQty': 100000}`.

### B — parallel is not simultaneous

`asyncio.gather` fires 100 coroutines at once, but the exchange has one book per
symbol and matches arrivals one at a time. The orders queue at the matching
engine and each one pays for the impact of the ones ahead of it: the ask walks
from $65,000 to $65,656 and the last account buys at the top. The $50k gap
between B and C is the entire cost of the "fire everything at once" design.

Depth is the reason. There are ~15 BTC within 0.1% of the touch; $10m is ~154
BTC. Ten times the resting liquidity has to come from somewhere, and it comes
from higher prices.

### C — slice it

Split the order over time and let market makers refill the ladder between
slices. Same $10m, 0.77 BTC more coin. Real desks go further — limit orders at
or inside the touch, randomised slice sizes, several venues — but the ordering
of the three results does not change.

## What this demo deliberately does not do

The script this came from gave each of 100 accounts its own API key and its own
proxy, commented `# prevents IP blocking`. That is not a rate-limit workaround;
splitting capital across accounts behind proxies to stay under an exchange's
per-account limits breaks Binance's terms of service and, depending on the
jurisdiction, runs into market-manipulation and KYC/AML rules. None of that is
modelled here, because per-account proxies would not help anyway: the
constraint is the shared order book, not the source IP.

If you want to move size on a real venue, the answer is a single account and a
good execution algorithm, or an OTC desk — which is what an OTC desk is *for*.

## Dashboard

`dashboard.html` is a standalone read-out of the same run — the price each order
paid by arrival position, the book depth against the size being asked for, and
what each account received for its $100,000. Open it in a browser; it carries
its own data and needs no server. `export_viz_data.py` regenerates that data
from the simulation.
