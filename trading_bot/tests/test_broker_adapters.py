from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlsplit

from trading_bot.brokers import BrokerError, OrderRequest, TradeRef
from trading_bot.brokers.bybit import BybitBroker, BybitKlineFeed, parse_kline_message, sign
from trading_bot.brokers.http import JsonHttpClient
from trading_bot.brokers.tradovate import (
    TradovateBroker,
    TradovateChartFeed,
    TradovateCredentials,
    chart_bars,
    parse_frame,
)
from trading_bot.config import Secret
from trading_bot.risk_manager import Direction, get_instrument
from trading_bot.strategies import Candle

M5 = timedelta(minutes=5)


class FakeHttp:
    """Scripted HTTP transport keyed by (method, path)."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, Any]]] = {}
        self.calls: list[tuple[str, str, dict[str, str], Any]] = []

    def add(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.routes.setdefault((method, path), []).append((status, payload))

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                 timeout: float) -> tuple[int, Mapping[str, str], bytes]:
        parts = urlsplit(url)
        path = parts.path.split("/v1", 1)[-1] if "/v1" in parts.path else parts.path
        self.calls.append((method, url, dict(headers), json.loads(body) if body else None))
        queue = self.routes.get((method, path))
        if not queue:
            return 404, {}, b'{"error":"no route"}'
        status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(payload, Exception):
            raise payload
        return status, {}, json.dumps(payload).encode()

    def last(self, method: str, path_part: str) -> tuple[str, dict[str, str], Any]:
        for m, url, headers, body in reversed(self.calls):
            if m == method and path_part in url:
                return url, headers, body
        raise AssertionError(f"no {method} {path_part}")


class HttpClientTests(unittest.TestCase):
    def test_reads_retry_orders_do_not(self) -> None:
        http = FakeHttp()
        http.add("GET", "/x", {"err": 1}, status=503)
        http.add("GET", "/x", {"ok": True})
        client = JsonHttpClient("https://h", transport=http, sleep=lambda _s: None)
        self.assertEqual(client.request("GET", "/x"), {"ok": True})
        http.add("POST", "/order", {"err": 1}, status=503)
        with self.assertRaises(BrokerError) as ctx:
            client.request("POST", "/order", body={})
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(sum(1 for c in http.calls if c[0] == "POST"), 1)  # never retried

    def test_client_errors_raise(self) -> None:
        http = FakeHttp()
        http.add("GET", "/bad", {"msg": "nope"}, status=400)
        with self.assertRaises(BrokerError) as ctx:
            JsonHttpClient("https://h", transport=http).request("GET", "/bad")
        self.assertFalse(ctx.exception.retryable)


class BybitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = FakeHttp()
        self.broker = BybitBroker({"acc": (Secret("KEY"), Secret("SECRET"))}, transport=self.http,
                                  clock_ms=lambda: 1_700_000_000_000)

    def ok(self, method: str, path: str, result: Any) -> None:
        self.http.add(method, path, {"retCode": 0, "retMsg": "OK", "result": result})

    def test_uses_testnet_and_signs_requests(self) -> None:
        self.ok("GET", "/v5/account/wallet-balance",
                {"list": [{"totalEquity": "101000.5", "totalWalletBalance": "100000"}]})
        snap = self.broker.account_snapshot("acc")
        self.assertEqual((snap.balance, snap.equity), (100000.0, 101000.5))
        url, headers, _ = self.http.last("GET", "wallet-balance")
        self.assertTrue(url.startswith("https://api-testnet.bybit.com/"))
        query = urlsplit(url).query
        self.assertEqual(headers["X-BAPI-SIGN"], sign("SECRET", "1700000000000", "KEY", "5000", query))
        self.assertEqual(headers["X-BAPI-API-KEY"], "KEY")

    def test_signature_matches_hmac_sha256(self) -> None:
        import hashlib
        import hmac

        expected = hmac.new(b"s", b"1k5000a=1", hashlib.sha256).hexdigest()
        self.assertEqual(sign("s", "1", "k", "5000", "a=1"), expected)

    def test_bracket_order_body(self) -> None:
        self.ok("POST", "/v5/order/create", {"orderId": "abc"})
        req = OrderRequest("acc", get_instrument("BTCUSDT"), Direction.SHORT, Decimal("0.405"),
                           Decimal("61200.0"), Decimal("58800.0"), "tbclient1", 60000.0)
        self.assertEqual(self.broker.place_bracket(req).broker_order_id, "abc")
        _, headers, body = self.http.last("POST", "order/create")
        self.assertEqual(body["side"], "Sell")
        self.assertEqual((body["qty"], body["stopLoss"], body["takeProfit"]), ("0.405", "61200.0", "58800.0"))
        self.assertEqual((body["orderType"], body["tpslMode"], body["orderLinkId"]), ("Market", "Full", "tbclient1"))
        raw = json.dumps(body, separators=(",", ":"))
        self.assertEqual(headers["X-BAPI-SIGN"], sign("SECRET", "1700000000000", "KEY", "5000", raw))

    def test_positions_close_and_closed_pnl(self) -> None:
        self.ok("GET", "/v5/position/list", {"list": [
            {"symbol": "BTCUSDT", "side": "Sell", "size": "0.4", "avgPrice": "60000"},
            {"symbol": "ETHUSDT", "side": "", "size": "0", "avgPrice": "0"}]})
        positions = self.broker.positions("acc")
        self.assertEqual(list(positions), ["BTCUSDT"])
        self.assertEqual(positions["BTCUSDT"].quantity, -0.4)
        self.ok("POST", "/v5/order/create", {"orderId": "close"})
        self.broker.close_position("acc", "BTCUSDT")
        _, _, body = self.http.last("POST", "order/create")
        self.assertEqual((body["side"], body["qty"], body["reduceOnly"]), ("Buy", "0.4", True))
        self.ok("GET", "/v5/position/closed-pnl", {"list": [
            {"closedPnl": "-120.5", "avgExitPrice": "60300", "updatedTime": "1700000100000"},
            # A reversal's previous close, just before our entry: must not count.
            {"closedPnl": "999", "avgExitPrice": "1", "updatedTime": "1699999999000"}]})
        since = datetime.fromtimestamp(1_700_000_000, timezone.utc)
        ref = TradeRef(Direction.SHORT, 0.4, 60000.0)
        closed = self.broker.closed_trade("acc", "BTCUSDT", since, ref)
        assert closed is not None
        self.assertEqual((closed.realized_pnl, closed.exit_price), (-120.5, 60300.0))

    def test_api_errors(self) -> None:
        self.http.add("GET", "/v5/account/wallet-balance", {"retCode": 10003, "retMsg": "invalid key"})
        with self.assertRaises(BrokerError) as ctx:
            self.broker.account_snapshot("acc")
        self.assertIn("invalid key", str(ctx.exception))
        with self.assertRaises(BrokerError):
            self.broker.account_snapshot("no-key-for-this")

    def test_kline_parsing_keeps_only_closed_bars(self) -> None:
        message = json.dumps({"topic": "kline.5.BTCUSDT", "type": "snapshot", "data": [
            {"start": 1700000000000, "end": 1700000299999, "interval": "5", "open": "60000",
             "close": "60100", "high": "60150", "low": "59950", "volume": "12.5", "confirm": True},
            {"start": 1700000300000, "open": "60100", "close": "60120", "high": "60130",
             "low": "60090", "volume": "1", "confirm": False}]})
        bars = parse_kline_message(message, M5)
        self.assertEqual(bars, [Candle("BTCUSDT", datetime.fromtimestamp(1700000000, timezone.utc), M5,
                                       60000, 60150, 59950, 60100, 12.5)])
        self.assertEqual(parse_kline_message('{"op":"pong"}', M5), [])
        self.assertEqual(parse_kline_message("not json", M5), [])

    def test_kline_feed_subscribes(self) -> None:
        feed = BybitKlineFeed(["BTCUSDT"], M5)
        self.assertEqual(feed.topics, ["kline.5.BTCUSDT"])
        with self.assertRaises(ValueError):
            BybitKlineFeed(["BTCUSDT"], timedelta(minutes=7))


class TradovateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = FakeHttp()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        self.http.add("POST", "/auth/accesstokenrequest",
                      {"accessToken": "TOKEN", "mdAccessToken": "MD", "expirationTime": future})
        self.http.add("GET", "/account/list", [{"id": 11, "name": "APEX-1"}, {"id": 12, "name": "APEX-2"}])
        self.http.add("GET", "/contract/find", {"id": 900, "name": "NQZ6"})
        creds = TradovateCredentials("user", Secret("pw"), "app", "1.0", "cid", Secret("sec"), "dev")
        self.broker = TradovateBroker(creds, {"NQ": "NQZ6"}, transport=self.http)

    def test_demo_endpoint_and_auth(self) -> None:
        self.broker.connect()
        url, _, body = self.http.last("POST", "accesstokenrequest")
        self.assertTrue(url.startswith("https://demo.tradovateapi.com/v1/"))
        self.assertEqual((body["name"], body["cid"], body["sec"]), ("user", "cid", "sec"))
        self.assertEqual(self.broker.auth.market_data_token(), "MD")

    def test_placeoso_bracket(self) -> None:
        self.http.add("POST", "/order/placeOSO", {"orderId": 5001, "oso1Id": 5002, "oso2Id": 5003})
        req = OrderRequest("APEX-2", get_instrument("NQ"), Direction.LONG, Decimal("2"),
                           Decimal("19980.00"), Decimal("20040.00"), "tbabc", 20000.0)
        self.assertEqual(self.broker.place_bracket(req).broker_order_id, "5001")
        _, headers, body = self.http.last("POST", "placeOSO")
        self.assertEqual(headers["Authorization"], "Bearer TOKEN")
        self.assertEqual((body["accountId"], body["symbol"], body["action"], body["orderQty"]),
                         (12, "NQZ6", "Buy", 2))
        self.assertTrue(body["isAutomated"])
        self.assertEqual(body["bracket1"], {"action": "Sell", "orderType": "Limit", "price": 20040.0})
        self.assertEqual(body["bracket2"], {"action": "Sell", "orderType": "Stop", "stopPrice": 19980.0})

    def test_order_rejection(self) -> None:
        self.http.add("POST", "/order/placeOSO", {"failureReason": "RiskRejected", "failureText": "margin"})
        req = OrderRequest("APEX-1", get_instrument("NQ"), Direction.SHORT, Decimal("1"),
                           Decimal("20020"), None, "t", 20000.0)
        with self.assertRaises(BrokerError) as ctx:
            self.broker.place_bracket(req)
        self.assertIn("RiskRejected", str(ctx.exception))

    def test_positions_snapshot_and_liquidate(self) -> None:
        self.http.add("GET", "/position/list", [
            {"accountId": 11, "contractId": 900, "netPos": -2, "netPrice": 20010.5},
            {"accountId": 12, "contractId": 900, "netPos": 1, "netPrice": 20000},
            {"accountId": 11, "contractId": 777, "netPos": 1, "netPrice": 1}])
        positions = self.broker.positions("APEX-1")
        self.assertEqual(list(positions), ["NQ"])
        self.assertEqual(positions["NQ"].quantity, -2)
        self.http.add("POST", "/cashBalance/getcashbalancesnapshot",
                      {"totalCashValue": 50100.0, "openPnL": -250.0})
        snap = self.broker.account_snapshot("APEX-1")
        self.assertEqual((snap.balance, snap.equity), (50100.0, 49850.0))
        self.http.add("POST", "/order/liquidatePosition", {"orderId": 1})
        self.broker.close_position("APEX-1", "NQ")
        _, _, body = self.http.last("POST", "liquidatePosition")
        self.assertEqual(body, {"accountId": 11, "contractId": 900, "admin": False})
        with self.assertRaises(BrokerError):
            self.broker.positions("NOPE")

    def test_closed_trade_from_exit_fills(self) -> None:
        self.http.add("GET", "/order/list", [{"id": 1, "accountId": 11}, {"id": 2, "accountId": 11},
                                             {"id": 3, "accountId": 12}, {"id": 4, "accountId": 11}])
        self.http.add("GET", "/fill/list", [
            # Previous long's exit, just before our entry (a reversal): ignored.
            {"orderId": 4, "contractId": 900, "timestamp": "2026-03-10T13:59:59.500Z", "action": "Sell", "qty": 1, "price": 19990.0},
            {"orderId": 1, "contractId": 900, "timestamp": "2026-03-10T14:00:01Z", "action": "Buy", "qty": 2, "price": 20000.25},
            {"orderId": 2, "contractId": 900, "timestamp": "2026-03-10T14:20:00Z", "action": "Sell", "qty": 1, "price": 20040.0},
            {"orderId": 2, "contractId": 900, "timestamp": "2026-03-10T14:20:01Z", "action": "Sell", "qty": 1, "price": 20041.0},
            {"orderId": 3, "contractId": 900, "timestamp": "2026-03-10T14:21:00Z", "action": "Sell", "qty": 5, "price": 1.0}])
        since = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
        closed = self.broker.closed_trade("APEX-1", "NQ", since, TradeRef(Direction.LONG, 2.0, 20000.25))
        assert closed is not None
        self.assertEqual(closed.exit_price, 20040.5)
        self.assertAlmostEqual(closed.realized_pnl, (20040.5 - 20000.25) * 2 * 20)
        # Only half the exit filled so far: not closed yet.
        partial = self.broker.closed_trade("APEX-1", "NQ", since, TradeRef(Direction.LONG, 3.0, 20000.25))
        self.assertIsNone(partial)

    def test_missing_contract_mapping(self) -> None:
        req = OrderRequest("APEX-1", get_instrument("MNQ"), Direction.LONG, Decimal("1"),
                           Decimal("19980"), None, "t", 20000.0)
        with self.assertRaises(BrokerError):
            self.broker.place_bracket(req)


class TradovateMarketDataTests(unittest.TestCase):
    def test_frames(self) -> None:
        self.assertEqual(parse_frame("o"), [])
        self.assertEqual(parse_frame("h"), [])
        self.assertEqual(parse_frame('a[{"s":200,"i":1}]'), [{"s": 200, "i": 1}])
        self.assertEqual(parse_frame("a[broken"), [])

    def test_chart_bars(self) -> None:
        items = [{"e": "chart", "d": {"charts": [{"id": 7, "bars": [
            {"timestamp": "2026-03-10T14:00:00.000Z", "open": 20000, "high": 20010, "low": 19990,
             "close": 20005, "upVolume": 10, "downVolume": 5}]}]}}]
        bars = chart_bars(items, {7: "NQ"}, M5)
        self.assertEqual(bars[0].symbol, "NQ")
        self.assertEqual(bars[0].volume, 15)
        self.assertEqual(chart_bars(items, {}, M5), [])

    def test_chart_feed_emits_only_closed_bars(self) -> None:
        class Auth:
            def market_data_token(self) -> str:
                return "MD"

        class Socket:
            def __init__(self) -> None:
                self.sent: list[str] = []

            def recv(self, timeout: float | None = None) -> str | None:
                return "o"

            def send_text(self, text: str) -> None:
                self.sent.append(text)

            def close(self) -> None:
                pass

        feed = TradovateChartFeed(Auth(), {"NQ": "NQZ6"}, ["NQ"], M5)  # type: ignore[arg-type]
        got: list[Candle] = []
        feed._sink = got.append
        ws = Socket()
        feed._on_open(ws)
        self.assertEqual(ws.sent[0], "authorize\n0\n\nMD")
        endpoint, request_id, _, body = ws.sent[1].split("\n", 3)
        self.assertEqual(endpoint, "md/getChart")
        self.assertEqual(json.loads(body)["chartDescription"]["elementSize"], 5)
        feed._on_message(f'a[{{"s":200,"i":{request_id},"d":{{"historicalId":3,"realtimeId":4}}}}]', ws)

        def chart(ts: str, close: float) -> str:
            return 'a[' + json.dumps({"e": "chart", "d": {"charts": [{"id": 4, "bars": [
                {"timestamp": ts, "open": 20000, "high": 20020, "low": 19990, "close": close}]}]}}) + ']'

        feed._on_message(chart("2026-03-10T14:00:00Z", 20001), ws)
        feed._on_message(chart("2026-03-10T14:00:00Z", 20008), ws)  # same bar, still forming
        self.assertEqual(got, [])
        feed._on_message(chart("2026-03-10T14:05:00Z", 20010), ws)
        self.assertEqual([c.close for c in got], [20008])


if __name__ == "__main__":
    unittest.main()
