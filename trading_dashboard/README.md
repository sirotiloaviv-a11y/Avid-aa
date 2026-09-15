# Avid Desk — multi-account trading console (MVP)

A single-file Streamlit app that puts a live chart, an execution ticket and a
multi-account risk monitor on one screen. Market data and broker responses are
simulated, so the whole thing runs with no broker credentials.

```bash
pip install -r requirements.txt      # streamlit + pandas, nothing else
streamlit run app.py
```

Then open http://localhost:8501. The chart library is pulled from a CDN at
render time, so the browser needs outbound access to `cdn.jsdelivr.net` (the
chart panel says so explicitly if it cannot load).

## What is on the screen

**Live chart** — TradingView Lightweight Charts, injected as HTML/JS through
`st.components.v1.html`, so there is no third-party Python wrapper to keep in
step with Streamlit releases. Candles, volume, master-account fill markers,
a dashed line at the average entry price and one per resting limit order.
Timeframes run from 1s to 5m; the zoom level survives the auto-refresh.

**Execution panel** — Buy/Long and Sell/Short against the charted instrument,
with quantity, market or limit, and a picker for which email sessions the
order is copied into. The notional preview re-prices as you type: master
quantity, and the summed child quantity after each sub-account's copy ratio.

**Sidebar** — accounts grouped by the email session they are logged in under.
Each session rolls up to its worst member's status (Active / Warning /
Disconnected / Kill switch). Each account shows equity, open PnL, open
positions and a drawdown bar against its own kill-switch budget, with
per-account Flatten / Kill / Re-arm and a desk-wide halt.

Below the fold: positions across every account, the full order blotter with
per-account latency and reject reasons, resting orders, and the system log.

## How the mock behaves

- **Feed.** A daemon thread walks each symbol with a mean-reverting geometric
  random walk at 4 ticks/second, and drops the "socket" roughly once every
  few minutes so reconnect-with-backoff is exercised. Raw ticks are kept and
  aggregated into bars on demand, which is why changing timeframe is instant.
- **Broker.** Every routed order goes through a simulated adapter with
  round-trip latency, a 6% reject rate and up to two retries with backoff.
  Rejects mark the account Warning; they never raise into the UI.
- **Copy distribution.** The master fills first. If the master does not get
  done, the fan-out is aborted rather than leaving sub-accounts holding risk
  the master does not have. Sub-accounts that are disconnected or killed are
  skipped with a reason, not silently dropped.
- **Risk.** Every tick marks each account to market, tracks its peak equity,
  and trips the kill switch when drawdown crosses that account's limit:
  positions are flattened at the mark, resting orders pulled, and the account
  locked out of further routing until it is re-armed.

## Going live

Two classes are the seam:

- `MarketDataFeed` — keep `snapshot`/`candles`, `last_price`, `marks`, `state`
  and `subscribe`, and point the producer at a real websocket.
- `OrderRouter._send_to_broker` — one method, one signature, returns a fill
  price or raises `BrokerError`. Everything above it (validation, master-first
  ordering, copy ratios, retries, blotter) is broker-agnostic.

`ACCOUNT_BLUEPRINT` and `SYMBOLS` at the top of `app.py` are the only other
things to edit.

## Tests

```bash
python test_engine.py
```

18 checks over position/PnL math, candle aggregation, copy distribution,
retries and rejects, limit-order matching and the kill switch. Streamlit and
pandas are stubbed, so the suite runs with nothing installed.
