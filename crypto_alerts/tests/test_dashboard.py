"""Dashboard tests against the real server on an ephemeral port, over a real socket."""

from __future__ import annotations

import asyncio
import json
import re
import unittest

from crypto_alerts.config import DashboardSettings
from crypto_alerts.dashboard import DashboardServer

from .helpers import long_setup
from .test_engine_and_config import make_engine


async def http(port, method, path, headers=None, body=b"", host="127.0.0.1"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    head = {"Host": f"{host}:{port}", **(headers or {})}
    if body:
        head["Content-Length"] = str(len(body))
    request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in head.items()) + "\r\n"
    writer.write(request.encode() + body)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    head_raw, _, payload = raw.partition(b"\r\n\r\n")
    lines = head_raw.decode().split("\r\n")
    status = int(lines[0].split()[1])
    headers_out = {k.lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
    return status, headers_out, payload


class DashboardTestCase(unittest.IsolatedAsyncioTestCase):
    token = ""

    async def asyncSetUp(self):
        self.engine, self.dispatcher = make_engine()
        self.server = DashboardServer(self.engine, DashboardSettings(port=0, token=self.token))
        _, self.port = await self.server.start()

    async def asyncTearDown(self):
        await self.server.close()

    async def page_csrf(self, headers=None):
        status, _, body = await http(self.port, "GET", "/", headers)
        self.assertEqual(status, 200)
        return re.search(rb'name="csrf-token" content="([^"]+)"', body).group(1).decode()

    async def post_risk(self, data, csrf, headers=None):
        hdrs = {"Content-Type": "application/json", "X-CSRF-Token": csrf, **(headers or {})}
        return await http(self.port, "POST", "/api/risk", hdrs, json.dumps(data).encode())


class LocalDashboardTests(DashboardTestCase):
    async def test_healthz(self):
        status, _, body = await http(self.port, "GET", "/healthz")
        self.assertEqual((status, body), (200, b"ok"))

    async def test_page_has_strict_security_headers(self):
        status, headers, body = await http(self.port, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Crypto Alerts", body)
        csp = headers["content-security-policy"]
        self.assertIn("script-src 'nonce-", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn(f'<script nonce="{nonce}">'.encode(), body)
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["cache-control"], "no-store")

    async def test_state_reflects_engine(self):
        await self.engine.process("BTC/USDT", long_setup())
        status, _, body = await http(self.port, "GET", "/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual(state["risk"]["account_equity"], 1_000_000)
        self.assertEqual(state["risk"]["risk_budget"], 5_000)
        self.assertEqual(state["alerts"][0]["symbol"], "BTC/USDT")
        self.assertEqual(state["alerts"][0]["status"], "sent")
        self.assertEqual(state["last_24h"]["alerts_sent"], 1)
        self.assertEqual(state["symbols"][0]["symbol"], "BTC/USDT")
        self.assertIn("delivery", state)

    async def test_risk_update_applies_live(self):
        csrf = await self.page_csrf()
        status, _, body = await self.post_risk({"account_equity": "250000", "risk_per_trade_pct": 1}, csrf)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["risk"], {"account_equity": 250_000, "risk_per_trade_pct": 1.0})
        self.assertEqual(self.engine.risk.risk_budget, 2_500)
        plan = await self.engine.process("BTC/USDT", long_setup())
        self.assertLessEqual(plan.risk_amount, 2_500)
        self.assertEqual(self.dispatcher.messages[0].kind, "system")  # change announced

    async def test_risk_update_rejects_bad_values(self):
        csrf = await self.page_csrf()
        for data in [{"account_equity": -5}, {"risk_per_trade_pct": 50}, {"account_equity": "lots"},
                     {"account_equity": True}, {}, ["list"]]:
            status, _, _ = await self.post_risk(data, csrf)
            self.assertIn(status, (400, 422), data)
        self.assertEqual(self.engine.risk.risk_budget, 5_000)

    async def test_risk_update_requires_csrf_token(self):
        status, _, _ = await self.post_risk({"account_equity": 1}, "wrong")
        self.assertEqual(status, 403)
        status, _, _ = await http(self.port, "POST", "/api/risk", {"Content-Type": "application/json"},
                                  b'{"account_equity": 1}')
        self.assertEqual(status, 403)
        self.assertEqual(self.engine.risk.settings.account_equity, 1_000_000)

    async def test_cross_origin_post_refused(self):
        csrf = await self.page_csrf()
        status, _, _ = await self.post_risk({"account_equity": 1}, csrf, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    async def test_dns_rebinding_host_refused(self):
        status, _, _ = await http(self.port, "GET", "/api/state", host="evil.example")
        self.assertEqual(status, 403)

    async def test_get_on_risk_and_unknown_routes(self):
        self.assertEqual((await http(self.port, "GET", "/api/risk"))[0], 405)
        self.assertEqual((await http(self.port, "GET", "/nope"))[0], 404)

    async def test_oversized_body_rejected(self):
        status, _, _ = await http(self.port, "POST", "/api/risk", {"Content-Type": "application/json"},
                                  b"x" * 10_000)
        self.assertEqual(status, 413)


class TokenDashboardTests(DashboardTestCase):
    token = "s3cret-token-value"

    async def test_requires_token(self):
        self.assertEqual((await http(self.port, "GET", "/"))[0], 401)
        self.assertEqual((await http(self.port, "GET", "/api/state"))[0], 401)
        self.assertEqual((await http(self.port, "GET", "/?token=wrong"))[0], 401)

    async def test_query_token_becomes_cookie(self):
        status, headers, _ = await http(self.port, "GET", f"/?token={self.token}")
        self.assertEqual(status, 302)
        self.assertEqual(headers["location"], "/")
        cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        session = cookie.split(";")[0]
        self.assertEqual((await http(self.port, "GET", "/api/state", {"Cookie": session}))[0], 200)

    async def test_query_token_not_accepted_on_api(self):
        self.assertEqual((await http(self.port, "GET", f"/api/state?token={self.token}"))[0], 401)

    async def test_bearer_token_and_any_host(self):
        auth = {"Authorization": f"Bearer {self.token}"}
        self.assertEqual((await http(self.port, "GET", "/api/state", auth, host="alerts.example.com"))[0], 200)
        csrf = await self.page_csrf(auth)
        status, _, _ = await self.post_risk({"risk_per_trade_pct": 0.25}, csrf, auth)
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.risk.settings.risk_per_trade_pct, 0.25)


if __name__ == "__main__":
    unittest.main()
