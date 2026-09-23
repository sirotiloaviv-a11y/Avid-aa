"""Real-time crypto trading alert system.

Watches exchange candles, runs a strategy on each closed candle, sizes the
trade to a fixed fraction of equity, and sends the plan to Telegram. It never
places orders.
"""

__version__ = "0.1.0"
