"""Bybit v5 adapter (USDT linear perpetuals) and public kline feed.

REST: https://bybit-exchange.github.io/docs/v5/intro
  * signing: HMAC-SHA256 over ``timestamp + api_key + recv_window + payload``,
    where payload is the query string (GET) or the exact JSON body (POST)
  * ``ENVIRONMENT=paper`` uses the testnet (api-testnet.bybit.com)

Orders are a market entry with position-level ``stopLoss`` / ``takeProfit``
(``tpslMode=Full``), so the protective stop lives on the exchange even if
the bot dies. ``orderLinkId`` carries our trade id.

This adapter assumes one-way position mode (``positionIdx=0``) and a unified
trading account. One API key = one account: each prop account needs its own
key (``BYBIT_KEYS``).

Validate on testnet before pointing it at a funded account: the request
shapes follow the published v5 docs but have not been run against the live
venue from this codebase.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, cast
from urllib.parse import urlencode

from ..config import Secret
from ..risk_manager.events import Direction
from ..risk_manager.position_sizing import AssetClass
from ..strategies.models import Candle
from ..utils.logger import get_logger
from ..utils.websocket import WebSocket
from .base import (
    AccountSnapshot,
    Broker,
    BrokerError,
    ClosedTrade,
    OrderAck,
    OrderRequest,
    Position,
    TradeRef,
)
from .http import HttpTransport, JsonHttpClient
from .streams import MessageSocket, ReconnectingStream

log = get_logger(__name__)

REST_LIVE = "https://api.bybit.com"
REST_TESTNET = "https://api-testnet.bybit.com"
WS_PUBLIC_LIVE = "wss://stream.bybit.com/v5/public/linear"
WS_PUBLIC_TESTNET = "wss://stream-testnet.bybit.com/v5/public/linear"
RECV_WINDOW = "5000"
CATEGORY = "linear"


def sign(secret: str, timestamp: str, api_key: str, recv_window: str, payload: str) -> str:
    message = f"{timestamp}{api_key}{recv_window}{payload}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class BybitBroker(Broker):
    name = "bybit"
    asset_class = AssetClass.CRYPTO

    def __init__(
        self,
        keys: Mapping[str, tuple[Secret, Secret]],
        *,
        testnet: bool = True,
        account_type: str = "UNIFIED",
        transport: HttpTransport | None = None,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        """``keys`` maps our broker-account label to (api_key, api_secret)."""
        self._keys = dict(keys)
        self.account_type = account_type
        self.http = JsonHttpClient(REST_TESTNET if testnet else REST_LIVE, transport=transport)
        self._clock_ms = clock_ms

    # -------------------------------------------------------------- calls
    def _creds(self, account: str) -> tuple[str, str]:
        try:
            key, secret = self._keys[account]
        except KeyError:
            raise BrokerError(f"no Bybit API key configured for account {account!r}") from None
        return key.get(), secret.get()

    def _call(self, account: str, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        api_key, secret = self._creds(account)
        timestamp = str(self._clock_ms())
        if method == "GET":
            query = urlencode(params)
            payload, body = query, None
        else:
            body = json.dumps(params, separators=(",", ":")).encode()
            payload, query = body.decode(), ""
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sign(secret, timestamp, api_key, RECV_WINDOW, payload),
        }
        result = self.http.request(method, path + (f"?{query}" if query else ""), headers=headers, raw_body=body)
        if not isinstance(result, dict):
            raise BrokerError(f"Bybit {path}: unexpected response")
        response = cast("dict[str, Any]", result)
        code = int(response.get("retCode", -1))
        if code != 0:
            # 10006: rate limit; 10002: timestamp outside recv window (clock drift).
            raise BrokerError(f"Bybit {path}: {code} {response.get('retMsg')}",
                              retryable=code in (10006, 10002, 10016))
        return cast("dict[str, Any]", response.get("result") or {})

    # ----------------------------------------------------------- interface
    def connect(self) -> None:
        for account in self._keys:
            self.account_snapshot(account)  # verifies keys and permissions

    def account_snapshot(self, account: str) -> AccountSnapshot:
        result = self._call(account, "GET", "/v5/account/wallet-balance", {"accountType": self.account_type})
        rows = cast("list[dict[str, Any]]", result.get("list") or [])
        if not rows:
            raise BrokerError("Bybit wallet-balance returned no account")
        row = rows[0]
        return AccountSnapshot(balance=float(row.get("totalWalletBalance") or 0),
                               equity=float(row.get("totalEquity") or 0))

    def positions(self, account: str) -> dict[str, Position]:
        result = self._call(account, "GET", "/v5/position/list", {"category": CATEGORY, "settleCoin": "USDT"})
        positions: dict[str, Position] = {}
        for row in cast("list[dict[str, Any]]", result.get("list") or []):
            size = float(row.get("size") or 0)
            if size == 0:
                continue
            sign_ = 1 if row.get("side") == "Buy" else -1
            symbol = str(row["symbol"])
            positions[symbol] = Position(symbol, size * sign_, float(row.get("avgPrice") or 0))
        return positions

    def place_bracket(self, order: OrderRequest) -> OrderAck:
        params: dict[str, Any] = {
            "category": CATEGORY,
            "symbol": order.symbol,
            "side": "Buy" if order.direction is Direction.LONG else "Sell",
            "orderType": "Market",
            "qty": format(order.quantity, "f"),
            "positionIdx": 0,
            "orderLinkId": order.client_id,
            "tpslMode": "Full",
            "stopLoss": format(order.stop_price, "f"),
            "slTriggerBy": "LastPrice",
        }
        if order.take_profit is not None:
            params["takeProfit"] = format(order.take_profit, "f")
            params["tpTriggerBy"] = "LastPrice"
        result = self._call(order.account, "POST", "/v5/order/create", params)
        return OrderAck(str(result.get("orderId", "")))

    def close_position(self, account: str, symbol: str) -> None:
        position = self.positions(account).get(symbol)
        if position is None:
            return
        self._call(account, "POST", "/v5/order/create", {
            "category": CATEGORY,
            "symbol": symbol,
            "side": "Sell" if position.quantity > 0 else "Buy",
            "orderType": "Market",
            "qty": format(Decimal(str(abs(position.quantity))), "f"),
            "positionIdx": 0,
            "reduceOnly": True,
        })

    def closed_trade(self, account: str, symbol: str, since: datetime, trade: TradeRef) -> ClosedTrade | None:
        start = int((since - timedelta(seconds=5)).timestamp() * 1000)
        result = self._call(account, "GET", "/v5/position/closed-pnl",
                            {"category": CATEGORY, "symbol": symbol, "startTime": start, "limit": 50})
        since_ms = int(since.timestamp() * 1000)
        # Strictly after our entry: a reversal's previous close lands just before it.
        rows = [r for r in cast("list[dict[str, Any]]", result.get("list") or [])
                if int(r.get("updatedTime") or r.get("createdTime") or 0) >= since_ms]
        if not rows:
            return None
        pnl = sum(float(r.get("closedPnl") or 0) for r in rows)
        latest = max(rows, key=lambda r: int(r.get("updatedTime") or r.get("createdTime") or 0))
        closed_ms = int(latest.get("updatedTime") or latest.get("createdTime") or 0)
        return ClosedTrade(symbol, float(latest.get("avgExitPrice") or 0) or None, pnl,
                           datetime.fromtimestamp(closed_ms / 1000, timezone.utc))


# ------------------------------------------------------------ market data
def parse_kline_message(message: str, timeframe: timedelta) -> list[Candle]:
    """Closed candles (``confirm: true``) from a ``kline.<interval>.<symbol>`` push."""
    try:
        data: Any = json.loads(message)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    msg = cast("dict[str, Any]", data)
    topic = str(msg.get("topic") or "")
    if not topic.startswith("kline."):
        return []
    symbol = topic.split(".", 2)[2]
    candles: list[Candle] = []
    for bar in cast("list[dict[str, Any]]", msg.get("data") or []):
        if not bar.get("confirm"):
            continue
        candles.append(Candle(
            symbol=symbol,
            start=datetime.fromtimestamp(int(bar["start"]) / 1000, timezone.utc),
            timeframe=timeframe,
            open=float(bar["open"]), high=float(bar["high"]), low=float(bar["low"]),
            close=float(bar["close"]), volume=float(bar.get("volume") or 0),
        ))
    return candles


class BybitKlineFeed:
    """Public (no key) kline stream for crypto symbols, auto-reconnecting."""

    def __init__(self, symbols: list[str], timeframe: timedelta, *, testnet: bool = True,
                 connect: Callable[[], MessageSocket] | None = None) -> None:
        minutes = int(timeframe.total_seconds() // 60)
        if minutes not in (1, 3, 5, 15, 30, 60, 120, 240, 360, 720):
            raise ValueError(f"Bybit has no {minutes}-minute kline interval")
        self.symbols = symbols
        self.timeframe = timeframe
        self.topics = [f"kline.{minutes}.{s}" for s in symbols]
        url = WS_PUBLIC_TESTNET if testnet else WS_PUBLIC_LIVE
        self._sink: Callable[[Candle], None] = lambda _c: None
        self.stream = ReconnectingStream(
            "bybit-kline",
            connect or (lambda: WebSocket.connect(url)),
            self._on_message,
            on_open=lambda ws: ws.send_text(json.dumps({"op": "subscribe", "args": self.topics})),
            heartbeat=lambda ws: ws.send_text('{"op":"ping"}'),
            heartbeat_interval=20.0,
            silence_timeout=90.0,
        )

    @property
    def connected(self) -> bool:
        return self.stream.connected

    def _on_message(self, message: str, _ws: MessageSocket) -> None:
        for candle in parse_kline_message(message, self.timeframe):
            self._sink(candle)

    def start(self, sink: Callable[[Candle], None]) -> None:
        self._sink = sink
        self.stream.start()

    def stop(self) -> None:
        self.stream.stop()
