"""Order execution through ccxt. Paper-trades when config.DRY_RUN is set."""

import logging

import ccxt

import config

log = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, dry_run: bool = config.DRY_RUN):
        self.dry_run = dry_run
        self.exchange = None
        self._sim_positions: dict[str, float] = {}   # dry-run net position per symbol
        if not dry_run:
            exchange_cls = getattr(ccxt, config.EXCHANGE_ID)
            self.exchange = exchange_cls(
                {
                    "apiKey": config.EXCHANGE_API_KEY,
                    "secret": config.EXCHANGE_API_SECRET,
                    "enableRateLimit": True,
                }
            )

    def market_order(self, symbol: str, side: str, amount: float, reduce_only: bool = False) -> dict:
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if self.dry_run:
            log.info("[DRY RUN] %s %s %s%s", side, amount, symbol, " (reduce-only)" if reduce_only else "")
            signed = amount if side == "buy" else -amount
            net = self._sim_positions.get(symbol, 0.0) + signed
            if abs(net) < 1e-12:
                self._sim_positions.pop(symbol, None)
            else:
                self._sim_positions[symbol] = net
            return {"id": "dry-run", "symbol": symbol, "side": side, "amount": amount, "status": "simulated"}
        params = {"reduceOnly": True} if reduce_only else {}
        return self.exchange.create_order(symbol, "market", side, amount, None, params)

    def close_all_positions(self) -> list[dict]:
        """Cancel all open orders and market-close every open position.

        Keeps going past individual failures so one bad symbol can't leave the
        rest of the book open. Returns one result dict per position.
        """
        if self.dry_run:
            positions = [
                {"symbol": s, "side": "long" if q > 0 else "short", "contracts": abs(q)}
                for s, q in self._sim_positions.items()
            ]
        else:
            try:
                self.exchange.cancel_all_orders()
            except Exception as exc:  # not every exchange supports a global cancel
                log.warning("cancel_all_orders failed: %s", exc)
            positions = self.exchange.fetch_positions()

        results = []
        for pos in positions:
            amount = abs(float(pos.get("contracts") or 0))
            if amount == 0:
                continue
            symbol = pos["symbol"]
            close_side = "sell" if pos.get("side") == "long" else "buy"
            try:
                order = self.market_order(symbol, close_side, amount, reduce_only=True)
                results.append({"symbol": symbol, "status": "closed", "order": order})
            except Exception as exc:
                log.error("Failed to close %s: %s", symbol, exc)
                results.append({"symbol": symbol, "status": "error", "error": str(exc)})
        return results
