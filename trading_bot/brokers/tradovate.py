"""Tradovate adapter (CME futures: NQ / MNQ) and chart market-data feed.

REST: https://api.tradovate.com
  * auth: ``POST /auth/accesstokenrequest`` → ``accessToken`` (orders/accounts)
    and ``mdAccessToken`` (market data); renewed before expiry
  * ``ENVIRONMENT=paper`` → demo.tradovateapi.com, ``live`` → live.tradovateapi.com
  * orders: ``POST /order/placeOSO``: a market entry whose fill activates a
    stop (and a limit target) on the exchange. ``isAutomated: true`` is set
    because CME rules require automated orders to be flagged.

Many futures prop firms (Apex, Topstep, Tradeify, ...) provision accounts on
Tradovate; several accounts under one login are addressed by account *name*.
Contracts are configured explicitly (``TRADOVATE_CONTRACTS=NQ:NQZ6``);
roll them before expiry.

Validate on the demo environment first: request shapes follow the published
API docs but have not been run against the live venue from this codebase.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, cast

from ..config import Secret
from ..risk_manager.events import Direction
from ..risk_manager.position_sizing import INSTRUMENTS, AssetClass
from ..strategies.candles import BarCloseDetector
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

REST_DEMO = "https://demo.tradovateapi.com/v1"
REST_LIVE = "https://live.tradovateapi.com/v1"
WS_MD = "wss://md.tradovateapi.com/v1/websocket"
RENEW_BEFORE = timedelta(minutes=15)


class TradovateCredentials:
    def __init__(self, username: str, password: Secret, app_id: str, app_version: str,
                 cid: str, secret: Secret, device_id: str) -> None:
        self.username = username
        self.password = password
        self.app_id = app_id
        self.app_version = app_version
        self.cid = cid
        self.secret = secret
        self.device_id = device_id


class TradovateAuth:
    """Holds access tokens and renews them before they expire. Thread-safe."""

    def __init__(self, http: JsonHttpClient, creds: TradovateCredentials,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.http = http
        self.creds = creds
        self._clock = clock
        self._lock = threading.Lock()
        self.access_token: str | None = None
        self.md_token: str | None = None
        self.expires: datetime | None = None

    def _store(self, result: Any) -> None:
        if not isinstance(result, dict):
            raise BrokerError("Tradovate auth: unexpected response")
        data = cast("dict[str, Any]", result)
        if "errorText" in data or "accessToken" not in data:
            # p-ticket / p-time: too many attempts, Tradovate asks us to wait.
            wait = data.get("p-time")
            raise BrokerError(f"Tradovate auth failed: {data.get('errorText') or 'no token'}",
                              retryable=wait is not None, retry_after=float(wait) if wait else None)
        self.access_token = str(data["accessToken"])
        self.md_token = str(data.get("mdAccessToken") or "") or None
        expiry = str(data.get("expirationTime") or "")
        self.expires = (datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                        if expiry else self._clock() + timedelta(minutes=80))

    def _login(self) -> None:
        c = self.creds
        self._store(self.http.request("POST", "/auth/accesstokenrequest", body={
            "name": c.username, "password": c.password.get(), "appId": c.app_id,
            "appVersion": c.app_version, "cid": c.cid, "sec": c.secret.get(), "deviceId": c.device_id,
        }))
        log.info("Tradovate: authenticated, token valid until %s", self.expires)

    def token(self) -> str:
        with self._lock:
            now = self._clock()
            if self.access_token is None or self.expires is None or now >= self.expires:
                self._login()
            elif self.expires - now < RENEW_BEFORE:
                try:
                    self._store(self.http.request("GET", "/auth/renewaccesstoken", headers=self._header()))
                except BrokerError as exc:
                    log.warning("Tradovate token renewal failed (%s); logging in again", exc)
                    self._login()
            assert self.access_token is not None
            return self.access_token

    def _header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def market_data_token(self) -> str:
        self.token()
        if not self.md_token:
            raise BrokerError("Tradovate login has no market data token (no data subscription?)")
        return self.md_token


class TradovateBroker(Broker):
    name = "tradovate"
    asset_class = AssetClass.FUTURES

    def __init__(
        self,
        creds: TradovateCredentials,
        contracts: Mapping[str, str],
        *,
        live: bool = False,
        transport: HttpTransport | None = None,
    ) -> None:
        """``contracts`` maps our symbol to the contract month, e.g. ``NQ -> NQZ6``."""
        self.http = JsonHttpClient(REST_LIVE if live else REST_DEMO, transport=transport)
        self.auth = TradovateAuth(self.http, creds)
        self.contracts = {k.upper(): v for k, v in contracts.items()}
        self._account_ids: dict[str, int] = {}
        self._contract_ids: dict[str, int] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------- calls
    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.http.request("GET", path, params=params,
                                 headers={"Authorization": f"Bearer {self.auth.token()}"})

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        result: Any = self.http.request("POST", path, body=dict(body),
                                        headers={"Authorization": f"Bearer {self.auth.token()}"})
        if not isinstance(result, dict):
            return result
        data = cast("dict[str, Any]", result)
        if "errorText" in data or data.get("failureReason"):
            raise BrokerError(f"Tradovate {path}: {data.get('errorText') or data.get('failureReason')} "
                              f"{data.get('failureText') or ''}".strip())
        return data

    def _account_id(self, account: str) -> int:
        with self._lock:
            if account not in self._account_ids:
                rows = cast("list[dict[str, Any]]", self._get("/account/list") or [])
                self._account_ids.update({str(r["name"]): int(r["id"]) for r in rows})
            try:
                return self._account_ids[account]
            except KeyError:
                raise BrokerError(f"Tradovate login has no account named {account!r}") from None

    def _contract(self, symbol: str) -> tuple[str, int]:
        name = self.contracts.get(symbol)
        if name is None:
            raise BrokerError(f"no Tradovate contract configured for {symbol} (TRADOVATE_CONTRACTS)")
        with self._lock:
            if name not in self._contract_ids:
                found = self._get("/contract/find", {"name": name})
                if not isinstance(found, dict) or "id" not in found:
                    raise BrokerError(f"Tradovate contract {name} not found")
                self._contract_ids[name] = int(cast("dict[str, Any]", found)["id"])
            return name, self._contract_ids[name]

    def _symbol_for_contract(self, contract_id: int) -> str | None:
        for symbol, name in self.contracts.items():
            if self._contract_ids.get(name) == contract_id:
                return symbol
        return None

    # ----------------------------------------------------------- interface
    def connect(self) -> None:
        self.auth.token()
        for symbol in self.contracts:
            self._contract(symbol)

    def account_snapshot(self, account: str) -> AccountSnapshot:
        snap = self._post("/cashBalance/getcashbalancesnapshot", {"accountId": self._account_id(account)})
        if not isinstance(snap, dict):
            raise BrokerError("Tradovate cash balance: unexpected response")
        data = cast("dict[str, Any]", snap)
        balance = float(data.get("totalCashValue") or 0)
        equity = float(data.get("netLiq") or balance + float(data.get("openPnL") or 0))
        return AccountSnapshot(balance, equity)

    def positions(self, account: str) -> dict[str, Position]:
        account_id = self._account_id(account)
        for symbol in self.contracts:
            self._contract(symbol)  # make sure ids are cached
        result: dict[str, Position] = {}
        for row in cast("list[dict[str, Any]]", self._get("/position/list") or []):
            if int(row.get("accountId", -1)) != account_id or not row.get("netPos"):
                continue
            symbol = self._symbol_for_contract(int(row["contractId"]))
            if symbol is not None:
                result[symbol] = Position(symbol, float(row["netPos"]), float(row.get("netPrice") or 0))
        return result

    def place_bracket(self, order: OrderRequest) -> OrderAck:
        contract, _ = self._contract(order.symbol)
        entry = "Buy" if order.direction is Direction.LONG else "Sell"
        exit_ = "Sell" if entry == "Buy" else "Buy"
        stop_leg = {"action": exit_, "orderType": "Stop", "stopPrice": float(order.stop_price)}
        body: dict[str, Any] = {
            "accountSpec": order.account,
            "accountId": self._account_id(order.account),
            "action": entry,
            "symbol": contract,
            "orderQty": int(order.quantity),
            "orderType": "Market",
            "isAutomated": True,
            "text": order.client_id[:64],
        }
        if order.take_profit is not None:
            body["bracket1"] = {"action": exit_, "orderType": "Limit", "price": float(order.take_profit)}
            body["bracket2"] = stop_leg
        else:
            body["bracket1"] = stop_leg
        result: Any = self._post("/order/placeOSO", body)
        data = cast("dict[str, Any]", result) if isinstance(result, dict) else {}
        order_id = data.get("orderId")
        if order_id is None:
            raise BrokerError(f"Tradovate placeOSO: no orderId in {str(data)[:200]}")
        return OrderAck(str(order_id))

    def close_position(self, account: str, symbol: str) -> None:
        _, contract_id = self._contract(symbol)
        # liquidatePosition also cancels the working bracket orders.
        self._post("/order/liquidatePosition",
                   {"accountId": self._account_id(account), "contractId": contract_id, "admin": False})

    def closed_trade(self, account: str, symbol: str, since: datetime, trade: TradeRef) -> ClosedTrade | None:
        """Exit fills (opposite side) after ``since`` that add up to the position.

        P&L is computed from our recorded entry price and excludes
        commissions; the account snapshot (what the risk engine uses) is the
        broker's own balance and includes them.
        """
        account_id = self._account_id(account)
        _, contract_id = self._contract(symbol)
        orders = {int(o["id"]) for o in cast("list[dict[str, Any]]", self._get("/order/list") or [])
                  if int(o.get("accountId", -1)) == account_id}
        exit_action = "Sell" if trade.direction is Direction.LONG else "Buy"
        exits = sorted(
            (f for f in cast("list[dict[str, Any]]", self._get("/fill/list") or [])
             if int(f.get("contractId", -1)) == contract_id and int(f.get("orderId", -1)) in orders
             and f.get("active", True) and f.get("action") == exit_action
             and _ts(f["timestamp"]) >= since),
            key=lambda f: str(f["timestamp"]),
        )
        filled = value = 0.0
        closed_at: datetime | None = None
        for fill in exits:
            take = min(float(fill["qty"]), trade.quantity - filled)
            filled += take
            value += take * float(fill["price"])
            closed_at = _ts(fill["timestamp"])
            if filled >= trade.quantity:
                break
        if filled < trade.quantity or closed_at is None or trade.entry_price is None:
            return None
        exit_price = value / filled
        spec = INSTRUMENTS[symbol]
        point_value = float(spec.tick_value / spec.tick_size)
        sign = 1 if trade.direction is Direction.LONG else -1
        pnl = (exit_price - trade.entry_price) * sign * filled * point_value
        return ClosedTrade(symbol, exit_price, pnl, closed_at)


def _ts(raw: Any) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


# ------------------------------------------------------------ market data
def parse_frame(frame: str) -> list[dict[str, Any]]:
    """Tradovate WS frames: ``o`` (open), ``h`` (heartbeat), ``a[...]`` (data), ``c`` (close)."""
    if not frame.startswith("a"):
        return []
    try:
        items: Any = json.loads(frame[1:])
    except json.JSONDecodeError:
        return []
    return [cast("dict[str, Any]", i) for i in cast("list[Any]", items) if isinstance(i, dict)] \
        if isinstance(items, list) else []


def chart_bars(items: list[dict[str, Any]], symbol_by_chart: Mapping[int, str],
               timeframe: timedelta) -> list[Candle]:
    """Bars (possibly still forming) from ``chart`` events."""
    candles: list[Candle] = []
    for item in items:
        if item.get("e") != "chart":
            continue
        payload = cast("dict[str, Any]", item.get("d") or {})
        for chart in cast("list[dict[str, Any]]", payload.get("charts") or []):
            symbol = symbol_by_chart.get(int(chart.get("id", -1)))
            if symbol is None:
                continue
            for bar in cast("list[dict[str, Any]]", chart.get("bars") or []):
                start = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
                candles.append(Candle(symbol, start, timeframe, float(bar["open"]), float(bar["high"]),
                                      float(bar["low"]), float(bar["close"]),
                                      float(bar.get("upVolume", 0)) + float(bar.get("downVolume", 0))))
    candles.sort(key=lambda c: c.start)
    return candles


class TradovateChartFeed:
    """Minute-bar chart subscription over the market-data WebSocket."""

    def __init__(self, auth: TradovateAuth, contracts: Mapping[str, str], symbols: list[str],
                 timeframe: timedelta, *, connect: Callable[[], MessageSocket] | None = None) -> None:
        self.auth = auth
        self.symbols = [s for s in symbols if s in contracts]
        self.contracts = dict(contracts)
        self.timeframe = timeframe
        self._sink: Callable[[Candle], None] = lambda _c: None
        self._request_id = 0
        self._pending_chart: dict[int, str] = {}   # request id -> symbol
        self._charts: dict[int, str] = {}          # chart id -> symbol
        self._closer = BarCloseDetector()
        self.stream = ReconnectingStream(
            "tradovate-md", connect or (lambda: WebSocket.connect(WS_MD)), self._on_message,
            on_open=self._on_open, heartbeat=lambda ws: ws.send_text("[]"),
            heartbeat_interval=2.5, silence_timeout=30.0,
        )

    @property
    def connected(self) -> bool:
        return self.stream.connected

    def _send(self, ws: MessageSocket, endpoint: str, body: Any = None) -> int:
        self._request_id += 1
        payload = "" if body is None else json.dumps(body)
        ws.send_text(f"{endpoint}\n{self._request_id}\n\n{payload}")
        return self._request_id

    def _on_open(self, ws: MessageSocket) -> None:
        self._charts.clear()
        self._pending_chart.clear()
        # First frame is "o"; then authorize with the market-data token.
        opened = ws.recv(timeout=10)
        if opened != "o":
            raise ConnectionError(f"unexpected first frame {opened!r}")
        ws.send_text(f"authorize\n0\n\n{self.auth.market_data_token()}")
        minutes = int(self.timeframe.total_seconds() // 60)
        for symbol in self.symbols:
            request = self._send(ws, "md/getChart", {
                "symbol": self.contracts[symbol],
                "chartDescription": {"underlyingType": "MinuteBar", "elementSize": minutes,
                                     "elementSizeUnit": "UnderlyingUnits", "withHistogram": False},
                "timeRange": {"asMuchAsElements": 2},
            })
            self._pending_chart[request] = symbol

    def _on_message(self, frame: str, _ws: MessageSocket) -> None:
        items = parse_frame(frame)
        for item in items:
            # Responses: {"s": 200, "i": request_id, "d": {"historicalId": .., "realtimeId": ..}}
            request_id = item.get("i")
            if isinstance(request_id, int) and request_id in self._pending_chart:
                symbol = self._pending_chart.pop(request_id)
                d = cast("dict[str, Any]", item.get("d") or {})
                for key in ("historicalId", "realtimeId"):
                    if key in d:
                        self._charts[int(d[key])] = symbol
        for candle in chart_bars(items, self._charts, self.timeframe):
            closed = self._closer.update(candle)
            if closed is not None:
                self._sink(closed)

    def start(self, sink: Callable[[Candle], None]) -> None:
        self._sink = sink
        self.stream.start()

    def stop(self) -> None:
        self.stream.stop()


def default_device_id() -> str:
    """Stable per-host id; Tradovate ties sessions to a device id."""
    import platform
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"trading-bot-{platform.node()}"))

