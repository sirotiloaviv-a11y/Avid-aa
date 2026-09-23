# crypto_alerts: real-time crypto trading alerts

Watches exchange candles in real time, runs a strategy on every **closed**
candle, sizes the trade to a fixed fraction of your equity, and sends the full
execution plan to Telegram. You place the order yourself. The system never
trades and never needs trading permissions.

```
🟢 LONG · BTC/USDT · 15m
⚡ RSI oversold + 3.4x Volume Surge + Support bounce

🎯 Entry: 63,912.40 – 64,050.00
      don't chase above 64,050.00
🛑 Stop Loss: 63,410.20 (−1.00%)
      swing low − 0.2 ATR
✅ Take Profit: 65,649.50 (+2.50%)
⚖️ Risk/Reward: 1 : 2.5

💰 Position Size
• Size: $500,547.05 (0.50x equity)
• Units: 7.81494217 BTC
• Loss at SL: $5,000.00 (0.50% of equity)
• Profit at TP: $12,500.00

📊 Trigger Reasons
• RSI oversold (27.3 < 30)
• 3.4x volume surge vs 20-candle average
• Bounce off support 63,520.00 (swing low)
```

## Quick start

```bash
pip install -r crypto_alerts/requirements.txt
cp crypto_alerts/.env.example crypto_alerts/.env   # then fill in Telegram token + chat id
DRY_RUN=true python -m crypto_alerts                # alerts print to the console first
python -m crypto_alerts                             # live
```

Tests use only the standard library (the exchange and bot are stubbed):

```bash
python -m unittest discover -s crypto_alerts/tests -t .
```

## Architecture

```
crypto_alerts/
├── config.py         Settings from env/.env, typed and validated (all errors reported at once)
├── market_data.py    ccxt.pro websocket / REST feed → closed-candle stream, reconnect + backfill
├── indicators.py     RSI, ATR (Wilder), EMA/SMA, volume ratio, swing highs/lows
├── strategy.py       Strategy base class + RsiVolumeReversalStrategy template
├── risk_manager.py   Stop loss, take profit, fixed-fractional position sizing
├── telegram_bot.py   HTML formatting, retrying Telegram notifier, non-blocking dispatch queue
├── main.py           AlertEngine wiring, per-symbol tasks, cooldown, graceful shutdown
└── tests/            70 unit + pipeline tests
```

```
exchange ──ws/REST──▶ MarketDataFeed ──closed candles──▶ compute_indicators
                                                              │
         Telegram ◀── AlertDispatcher ◀── format_alert ◀── RiskManager ◀── Strategy
```

Each symbol runs in its own asyncio task on one shared exchange connection.
Alerts go through a queue, so a slow or rate-limited Telegram never delays
market data.

## How it decides

**Closed candles only.** A candle counts as closed once the next one has
opened. Evaluating a forming candle gives alerts whose RSI and volume change a
minute later, so this system never does it. Stale candles (for example after a
long outage) are skipped because they are no longer actionable.

**Long trigger** (template): RSI < 30, volume ≥ 2.5× the average of the
previous 20 candles, and the candle's low comes within `SR_TOLERANCE_ATR` of a
prior confirmed swing low, then closes above it with a bullish reaction (a
green close, or a lower wick at least half the candle's range).
**Short** is the mirror image at a swing high. Every threshold is in `.env`.

**Stop loss** (`STOP_MODE`):
- `atr`: entry ∓ `ATR_STOP_MULTIPLIER` × ATR
- `swing`: beyond the invalidation level (the further of the wick and the
  S/R level) by `SWING_BUFFER_ATR` × ATR
- `hybrid` (default): the swing stop, widened to `MIN_STOP_ATR` if it sits
  inside normal noise, and replaced by the ATR stop if it is further than
  `MAX_STOP_ATR`

**Take profit**: entry ± `RISK_REWARD_RATIO` × stop distance.

**Position size**: `units = ACCOUNT_EQUITY × RISK_PER_TRADE_PCT / 100 / |entry − stop|`.
A fill at the reference entry that hits the stop loses exactly the budget
($5,000 on $1M at 0.5%). Three settings adjust this, and each can only make
the realised risk *smaller*. The alert shows the resulting figure:
- `FEE_RATE_PCT`: the budget includes entry and exit fees
- quantity is rounded **down** to the exchange's lot step
- `MAX_LEVERAGE` caps notional on very tight stops, and the alert flags when it applies

The entry zone lies only on the favourable side of the signal price, so any
fill inside it risks at most the budget. The alert tells you not to chase
beyond it.

## Reliability

- Network errors, exchange downtime and silent websockets (`STREAM_TIMEOUT_SECONDS`)
  trigger reconnects with exponential backoff and jitter, plus a REST backfill
  so indicators are never computed across a gap.
- Unrecoverable errors (unknown or delisted symbol, bad API key) stop only the
  affected symbol and send a Telegram notice. The others keep running.
- An exception while evaluating a candle is logged and skipped. It never kills
  the stream.
- Telegram sends are retried and honour flood-control `retry_after`. Permanent
  errors (such as a bad chat id) are not retried.
- Per symbol/direction cooldown (`ALERT_COOLDOWN_MINUTES`) prevents alert spam.
- SIGINT/SIGTERM drain queued alerts and close the exchange connection cleanly.

## Adding a strategy

Subclass `Strategy`, implement `evaluate(symbol, timeframe, frame) -> Signal | None`
using the series in `IndicatorFrame`, and pass it to `AlertEngine` in
`main.run`. Set `invalidation_level` to where the idea is wrong. The risk
manager derives the stop, target and size from it.

## Caveats

- Perpetual symbols use ccxt's unified form, e.g. `BTC/USDT:USDT` on Bybit or
  Binance with `MARKET_TYPE=swap`. Inverse (coin-margined) contracts are rejected.
- Units are in the base asset (BTC, ETH, ...), which is what the Binance and
  Bybit apps take as quantity.
- The bundled strategy is a template to build on, not a tested edge. Paper
  trade it (`DRY_RUN=true`) before you size real money from it.
