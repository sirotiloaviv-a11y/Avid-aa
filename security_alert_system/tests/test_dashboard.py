"""Tests for the runtime state layer and the HTTP dashboard.

The dashboard tests start the real server on an ephemeral port and talk to it
over a real socket, so the hand-rolled HTTP handling is actually exercised.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from security_alert_system.alerts import Alert
from security_alert_system.dashboard import DashboardServer, render_page
from security_alert_system.keywords import KeywordMatcher
from security_alert_system.monitoring import Runtime, SourceHealth


def make_alert(text: str = "פיגוע ירי", source: str = "ynet") -> Alert:
    return Alert(
        source=source,
        source_kind="rss",
        title=text,
        body=text,
        matches=KeywordMatcher().find_all(text),
        url="https://example.com/a",
    )


class TestSourceHealth(unittest.TestCase):
    def test_status_transitions(self):
        health = SourceHealth("feed", "rss")
        self.assertEqual(health.status, "pending")

        health.record_success(items=5)
        self.assertEqual(health.status, "ok")
        self.assertEqual(health.items_seen, 5)

        health.record_error("boom")
        self.assertEqual(health.status, "degraded")

        health.record_error("boom")
        health.record_error("boom")
        self.assertEqual(health.status, "down")
        self.assertEqual(health.consecutive_errors, 3)

        health.record_success()
        self.assertEqual(health.status, "ok")
        self.assertEqual(health.consecutive_errors, 0)

    def test_error_message_is_truncated(self):
        health = SourceHealth("feed", "rss")
        health.record_error("x" * 1000)
        self.assertLessEqual(len(health.last_error_message), 300)


class TestRuntime(unittest.TestCase):
    def test_records_alerts_and_counts(self):
        runtime = Runtime()
        runtime.source("ynet", "rss")
        runtime.record_alert(make_alert(), delivered=True)
        runtime.record_alert(make_alert(), delivered=False)

        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["alerts_sent"], 1)
        self.assertEqual(snapshot["alerts_failed"], 1)
        self.assertEqual(len(snapshot["alerts"]), 2)
        self.assertEqual(snapshot["by_severity"]["CRITICAL"], 2)
        self.assertEqual(runtime.sources["ynet"].alerts_raised, 2)

    def test_history_is_bounded_and_newest_first(self):
        runtime = Runtime(history_size=3)
        for i in range(5):
            runtime.record_alert(make_alert(f"פיגוע {i}"), delivered=True)
        titles = [a.title for a in runtime.alerts]
        self.assertEqual(len(titles), 3)
        self.assertEqual(titles[0], "פיגוע 4")

    def test_history_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.json"
            first = Runtime(history_size=10, path=path)
            first.record_alert(make_alert("פיגוע בצומת"), delivered=True)

            second = Runtime(history_size=10, path=path)
            self.assertEqual(len(second.alerts), 1)
            self.assertEqual(second.alerts[0].title, "פיגוע בצומת")
            self.assertEqual(second.alerts_sent, 1)

    def test_corrupt_history_file_is_survivable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.json"
            path.write_text("{not json", encoding="utf-8")
            # Warns, then starts empty rather than refusing to boot.
            with self.assertLogs("security_alert_system.monitoring", "WARNING"):
                runtime = Runtime(path=path)
            self.assertEqual(len(runtime.alerts), 0)

    def test_rename_source_merges_counters(self):
        runtime = Runtime()
        runtime.source("https://feed.url", "rss").record_success(items=3)
        runtime.rename_source("https://feed.url", "ynet — ביטחון")

        self.assertNotIn("https://feed.url", runtime.sources)
        self.assertEqual(runtime.sources["ynet — ביטחון"].items_seen, 3)
        self.assertEqual(runtime.sources["ynet — ביטחון"].name, "ynet — ביטחון")

    def test_snapshot_is_json_serialisable(self):
        runtime = Runtime()
        runtime.source("ynet", "rss").record_success(items=2)
        runtime.record_alert(make_alert(), delivered=True)
        json.dumps(runtime.snapshot(), ensure_ascii=False)  # must not raise


class DashboardTestCase(unittest.IsolatedAsyncioTestCase):
    token = ""

    async def asyncSetUp(self):
        self.runtime = Runtime()
        self.runtime.source("ynet", "rss").record_success(items=4)
        self.runtime.record_alert(make_alert(), delivered=True)

        self.stop = asyncio.Event()
        self.server = DashboardServer(
            self.runtime, "127.0.0.1", 0, self.token,
            context={"keyword_count": 60, "feed_count": 5},
        )
        # Bind on an ephemeral port, then read back what the OS assigned.
        self._real_start = asyncio.start_server
        self.port: int | None = None

        async def capture(handler, host, port):
            server = await self._real_start(handler, host, port)
            self.port = server.sockets[0].getsockname()[1]
            return server

        asyncio.start_server = capture  # type: ignore[assignment]
        self.task = asyncio.create_task(self.server.run(self.stop))
        for _ in range(50):
            if self.port:
                break
            await asyncio.sleep(0.02)
        asyncio.start_server = self._real_start  # type: ignore[assignment]
        self.assertIsNotNone(self.port, "dashboard did not bind")

    async def asyncTearDown(self):
        self.stop.set()
        await asyncio.wait_for(self.task, timeout=5)

    async def request(self, path: str, headers: str = "") -> tuple[int, dict[str, str], str]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        await writer.wait_closed()

        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1])
        headers_out = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers_out[name.strip().lower()] = value.strip()
        return status, headers_out, body.decode("utf-8")


class TestDashboardRoutes(DashboardTestCase):
    async def test_healthz(self):
        status, _, body = await self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok")

    async def test_status_json(self):
        status, headers, body = await self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["content-type"])

        data = json.loads(body)
        self.assertEqual(data["alerts_sent"], 1)
        self.assertEqual(data["sources"][0]["name"], "ynet")
        self.assertEqual(data["sources"][0]["status"], "ok")
        self.assertEqual(data["alerts"][0]["severity"], "CRITICAL")
        self.assertEqual(data["config"]["keyword_count"], 60)

    async def test_index_serves_html(self):
        status, headers, body = await self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn('dir="rtl"', body)
        self.assertIn("nosniff", headers["x-content-type-options"])

    async def test_unknown_path_404(self):
        status, _, _ = await self.request("/nope")
        self.assertEqual(status, 404)

    async def _post(self, path: str, body: bytes = b"{}", auth: str = "") -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        head = (
            f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Length: {len(body)}\r\n{auth}\r\n"
        ).encode()
        writer.write(head + body)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        await writer.wait_closed()
        return raw

    async def test_post_to_a_read_path_is_not_found(self):
        # POST is a valid method now, but only on /ingest.
        raw = await self._post("/")
        self.assertIn(b"404", raw.split(b"\r\n")[0])

    async def test_ingest_is_unavailable_when_not_configured(self):
        # No pipeline and no token: the route must not fall open, and must not
        # pretend to accept either.
        raw = await self._post("/ingest", b'{"source":"x","text":"y"}')
        self.assertIn(b"503", raw.split(b"\r\n")[0])

    async def test_garbage_request_does_not_kill_server(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"\xff\xfe nonsense\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        await writer.wait_closed()

        status, _, body = await self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok")


class TestDashboardAuth(DashboardTestCase):
    token = "s3cret-token"

    async def test_status_requires_token(self):
        status, _, _ = await self.request("/api/status")
        self.assertEqual(status, 401)

    async def test_query_token_accepted(self):
        status, _, _ = await self.request(f"/api/status?token={self.token}")
        self.assertEqual(status, 200)

    async def test_bearer_token_accepted(self):
        status, _, _ = await self.request(
            "/api/status", headers=f"Authorization: Bearer {self.token}\r\n"
        )
        self.assertEqual(status, 200)

    async def test_wrong_token_rejected(self):
        status, _, _ = await self.request("/api/status?token=wrong")
        self.assertEqual(status, 401)

    async def test_healthz_stays_open(self):
        # A container healthcheck must not need the secret.
        status, _, body = await self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok")

    async def test_page_carries_token_to_its_own_fetch(self):
        status, _, body = await self.request(f"/?token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn(f"?token={self.token}", body)


class TestPageRendering(unittest.TestCase):
    def test_token_placeholder_is_replaced(self):
        self.assertNotIn("__TOKEN_QUERY__", render_page("?token=abc"))
        self.assertIn("?token=abc", render_page("?token=abc"))

    def test_empty_token_leaves_clean_url(self):
        page = render_page("")
        self.assertNotIn("__TOKEN_QUERY__", page)
        self.assertIn('TOKEN_QUERY = ""', page)


if __name__ == "__main__":
    unittest.main()
