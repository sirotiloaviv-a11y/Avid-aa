"""Tests for the ingest pipe — the one write route into the system.

Half of these are about the pipeline logic and half about the HTTP route,
which is exercised over a real socket because it is hand-rolled and it is the
only place an outside process can cause this system to act.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from security_alert_system.config import Config
from security_alert_system.dashboard import DashboardServer
from security_alert_system.ingest import RATE_LIMIT_PER_MINUTE, IngestPipeline
from security_alert_system.monitoring import Runtime
from security_alert_system.notifier import Notifier
from security_alert_system.state import StateStore


class StubTelegram:
    def __init__(self):
        self.messages: list[str] = []

    async def send_message(self, chat_id, text, **_kw):
        self.messages.append(text)
        return {"message_id": len(self.messages)}

    async def send_photo(self, *a, **k):
        return {}


class PipelineCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config()
        self.telegram = StubTelegram()
        self.runtime = Runtime(history_size=50)
        self.state = StateStore(Path(self.tmp.name) / "seen.json")
        self.pipeline = IngestPipeline(
            self.config,
            # runtime goes to the Notifier as it does in main.py — alert
            # history is recorded there for every source uniformly.
            Notifier(self.telegram, "42", runtime=self.runtime),
            self.state,
            self.runtime,
        )

    def tearDown(self):
        self.tmp.cleanup()


class TestIngestPipeline(PipelineCase):
    async def test_keyword_hit_becomes_an_alert(self):
        result = await self.pipeline.submit(
            source="וואטסאפ · שכונה",
            text="שמעתי פיצוץ חזק ליד הצומת",
            kind="whatsapp",
        )
        self.assertTrue(result.accepted)
        self.assertTrue(result.matched)
        self.assertTrue(result.alerted)
        self.assertEqual(result.severity, "HIGH")
        self.assertIn("פיצוץ", result.phrases)
        self.assertIn("וואטסאפ", self.telegram.messages[0])

    async def test_non_matching_text_is_accepted_but_silent(self):
        result = await self.pipeline.submit(source="וואטסאפ", text="מי אוסף את הילדים היום")
        self.assertTrue(result.accepted)
        self.assertFalse(result.matched)
        self.assertEqual(self.telegram.messages, [])

    async def test_external_source_reaches_the_dashboard(self):
        await self.pipeline.submit(source="וואטסאפ · שכונה", text="פיגוע בצומת", kind="whatsapp")
        snapshot = self.runtime.snapshot()
        names = [s["name"] for s in snapshot["sources"]]
        self.assertIn("וואטסאפ · שכונה", names)
        self.assertEqual(snapshot["alerts"][0]["source_kind"], "whatsapp")

    async def test_alert_count_is_not_double_reported(self):
        # The pipeline records source health and the notifier records alert
        # history; only one of them may own alerts_raised, or every external
        # alert shows up twice on the dashboard.
        await self.pipeline.submit(source="וואטסאפ", text="פיגוע בצומת")
        self.assertEqual(self.runtime.sources["וואטסאפ"].alerts_raised, 1)

    async def test_same_message_twice_alerts_once(self):
        # A bridge restarting and replaying its backlog must not re-alert.
        for _ in range(3):
            await self.pipeline.submit(
                source="וואטסאפ", text="פיגוע בצומת", external_id="wamid.ABC"
            )
        self.assertEqual(len(self.telegram.messages), 1)

    async def test_dedupe_falls_back_to_content_without_an_id(self):
        for _ in range(2):
            await self.pipeline.submit(source="וואטסאפ", text="פיגוע בצומת")
        self.assertEqual(len(self.telegram.messages), 1)

    async def test_same_text_from_two_sources_is_not_collapsed(self):
        # Two independent groups reporting the same thing is corroboration,
        # not a duplicate — the dedupe key is scoped to the source.
        await self.pipeline.submit(source="קבוצה א", text="פיגוע בצומת")
        await self.pipeline.submit(source="קבוצה ב", text="פיגוע בצומת")
        self.assertEqual(len(self.telegram.messages), 2)

    async def test_missing_fields_are_rejected(self):
        self.assertFalse((await self.pipeline.submit(source="", text="פיגוע")).accepted)
        self.assertFalse((await self.pipeline.submit(source="x", text="  ")).accepted)

    async def test_rate_limit_protects_the_alert_budget(self):
        for i in range(RATE_LIMIT_PER_MINUTE):
            await self.pipeline.submit(source="loop", text=f"הודעה {i}")
        result = await self.pipeline.submit(source="loop", text="הודעה נוספת")
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "rate limited")

    async def test_rate_limit_is_per_source(self):
        for i in range(RATE_LIMIT_PER_MINUTE):
            await self.pipeline.submit(source="noisy", text=f"הודעה {i}")
        # A misbehaving bridge must not silence a well-behaved one.
        result = await self.pipeline.submit(source="quiet", text="פיגוע בצומת")
        self.assertTrue(result.accepted)
        self.assertTrue(result.alerted)

    async def test_oversized_text_is_truncated_not_rejected(self):
        result = await self.pipeline.submit(source="x", text="פיגוע " + "א" * 50_000)
        self.assertTrue(result.accepted)
        self.assertTrue(result.matched)


class TestIngestRoute(unittest.IsolatedAsyncioTestCase):
    """The HTTP surface, over a real socket."""

    TOKEN = "ingest-secret"

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.telegram = StubTelegram()
        runtime = Runtime(history_size=50)
        self.pipeline = IngestPipeline(
            Config(), Notifier(self.telegram, "42", runtime=runtime),
            StateStore(Path(self.tmp.name) / "seen.json"), runtime,
        )
        self.stop = asyncio.Event()
        server = DashboardServer(
            runtime, "127.0.0.1", 0, token="",
            ingest=self.pipeline, ingest_token=self.TOKEN,
        )
        real = asyncio.start_server
        self.port = None

        async def capture(handler, host, port):
            srv = await real(handler, host, port)
            self.port = srv.sockets[0].getsockname()[1]
            return srv

        asyncio.start_server = capture  # type: ignore[assignment]
        self.task = asyncio.create_task(server.run(self.stop))
        for _ in range(50):
            if self.port:
                break
            await asyncio.sleep(0.02)
        asyncio.start_server = real  # type: ignore[assignment]

    async def asyncTearDown(self):
        self.stop.set()
        await asyncio.wait_for(self.task, timeout=5)
        self.tmp.cleanup()

    async def post(self, payload, token=TOKEN, raw_body=None):
        body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
        auth = f"Authorization: Bearer {token}\r\n" if token else ""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(
            f"POST /ingest HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n{auth}\r\n".encode() + body
        )
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        await writer.wait_closed()
        head, _, out = raw.partition(b"\r\n\r\n")
        status = int(head.decode("latin-1").split("\r\n")[0].split()[1])
        return status, out.decode("utf-8")

    async def test_authorised_push_alerts(self):
        status, body = await self.post(
            {"source": "וואטסאפ · שכונה", "text": "פיגוע בצומת", "kind": "whatsapp"}
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["alerted"])
        self.assertEqual(data["severity"], "CRITICAL")
        self.assertEqual(len(self.telegram.messages), 1)

    async def test_no_token_is_rejected(self):
        status, _ = await self.post({"source": "x", "text": "פיגוע"}, token="")
        self.assertEqual(status, 401)
        self.assertEqual(self.telegram.messages, [])

    async def test_wrong_token_is_rejected(self):
        status, _ = await self.post({"source": "x", "text": "פיגוע"}, token="guess")
        self.assertEqual(status, 401)
        self.assertEqual(self.telegram.messages, [])

    async def test_malformed_json_is_a_400_not_a_crash(self):
        status, _ = await self.post(None, raw_body=b"{not json")
        self.assertEqual(status, 400)
        # Server is still alive afterwards.
        status2, _ = await self.post({"source": "x", "text": "פיגוע"})
        self.assertEqual(status2, 200)

    async def test_non_object_body_is_rejected(self):
        status, _ = await self.post(None, raw_body=b'["a","b"]')
        self.assertEqual(status, 400)

    async def test_oversized_body_is_rejected_without_reading_it(self):
        # The server answers 413 from the Content-Length header alone and does
        # not drain the body, so a large write may be reset mid-flight. Either
        # a clean 413 or a reset is correct; what matters is that the payload
        # is never buffered and the server survives.
        try:
            status, _ = await self.post(None, raw_body=b"x" * (300 * 1024))
            self.assertEqual(status, 413)
        except (ConnectionResetError, BrokenPipeError):
            pass
        status2, _ = await self.post({"source": "x", "text": "פיגוע"})
        self.assertEqual(status2, 200)

    async def test_missing_source_is_reported_not_alerted(self):
        status, body = await self.post({"text": "פיגוע בצומת"})
        self.assertEqual(status, 400)
        self.assertIn("source is required", json.loads(body)["reason"])

    async def test_healthz_still_works_alongside_ingest(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout=5)
        writer.close()
        await writer.wait_closed()
        self.assertIn(b"200", raw.split(b"\r\n")[0])


class TestIngestConfigValidation(unittest.TestCase):
    def _config(self, **kw):
        config = Config()
        config.bot_token, config.alert_chat_id = "t", "1"
        config.ingest_enabled = True
        for key, value in kw.items():
            setattr(config, key, value)
        return config

    def test_enabled_without_token_is_rejected(self):
        problems = self._config(ingest_token="").validate()
        self.assertTrue(any("INGEST_TOKEN" in p for p in problems))

    def test_token_must_differ_from_the_dashboard_token(self):
        config = self._config(ingest_token="same", dashboard_token="same")
        self.assertTrue(any("must differ" in p for p in config.validate()))

    def test_ingest_requires_the_dashboard_server(self):
        config = self._config(ingest_token="tok", dashboard_enabled=False)
        self.assertTrue(any("requires DASHBOARD_ENABLED" in p for p in config.validate()))


if __name__ == "__main__":
    unittest.main()
