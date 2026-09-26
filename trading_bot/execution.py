"""Order execution through ccxt. Paper-trades when config.DRY_RUN is set."""

import logging

import ccxt

import config

log = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, dry_run: bool = config.DRY_RUN):
        self.dry_run = dry_run
        self.exchange = None
        if not dry_run:
            exchange_cls = getattr(ccxt, config.EXCHANGE_ID)
            self.exchange = exchange_cls(
                {
                    "apiKey": config.EXCHANGE_API_KEY,
                    "secret": config.EXCHANGE_API_SECRET,
                    "enableRateLimit": True,
                }
            )

    def market_order(self, symbol: str, side: str, amount: float) -> dict:
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if self.dry_run:
            log.info("[DRY RUN] %s %s %s", side, amount, symbol)
            return {"id": "dry-run", "symbol": symbol, "side": side, "amount": amount, "status": "simulated"}
        return self.exchange.create_order(symbol, "market", side, amount)
