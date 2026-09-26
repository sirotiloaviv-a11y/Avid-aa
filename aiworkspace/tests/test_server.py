"""End-to-end API tests against a real server on an ephemeral loopback port.
Uses the demo provider or a scripted fake; no network access."""

import http.client
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from aiworkspace.chat import build_context
from aiworkspace.config import load_settings
from aiworkspace.providers.base import (
    ProviderError,
    ResponseStart,
    StreamEnd,
    TextDelta,
)
from aiworkspace.providers.demo import DemoProvider
from aiworkspace.server import App, make_server
from aiworkspace.store import Message


class ScriptedProvider:
    name = "scripted"
    model = "scripted-1"
    simulated = False

    def __init__(
        self, chunks=("Hi", " there"), error=None, gate=None, end=StreamEnd("end_turn")
    ):
        self.chunks = chunks
        self.error = error
        self.gate = gate
        self.end = end
        self.calls = []

    def stream(self, system, turns, max_tokens, cancel, deadline):
        self.calls.append(turns)
        yield ResponseStart("served-model-7", 21)
        for i, chunk in enumerate(self.chunks):
            if self.gate is not None and i == 1:
                self.gate.wait(5)
            if cancel.is_set():
                yield StreamEnd("cancelled")
                return
            yield TextDelta(chunk)
        if self.error:
            raise self.error
        yield self.end


class ServerTestCase(unittest.TestCase):
    provider = None
    overrides: dict = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "db.sqlite3"
        self.start(self.provider or DemoProvider(delay_s=0))

    def start(self, provider):
        settings = replace(
            load_settings({}, env_file=None), db_path=self.db, **self.overrides
        )
        self.app = App(settings, provider=provider)
        self.server = make_server(self.app, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None, csrf=True, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if csrf and method != "GET":
            h["X-AIWS-Request"] = "1"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp, payload

    def json(self, method, path, body=None, **kw):
        resp, payload = self.request(method, path, body, **kw)
        return resp.status, json.loads(payload) if payload else None

    def new_conversation(self):
        status, data = self.json("POST", "/api/conversations", {})
        self.assertEqual(status, 201)
        return data["conversation"]["id"]

    def send(self, cid, content):
        resp, payload = self.request(
            "POST", f"/api/conversations/{cid}/messages", {"content": content}
        )
        events = []
        if resp.getheader("Content-Type", "").startswith("text/event-stream"):
            for block in payload.decode().split("\n\n"):
                lines = [
                    ln for ln in block.split("\n") if ln and not ln.startswith(":")
                ]
                if not lines:
                    continue
                name = lines[0].removeprefix("event: ")
                events.append((name, json.loads(lines[1].removeprefix("data: "))))
        return resp, events


class ConversationFlowTest(ServerTestCase):
    def test_full_flow_create_send_reopen_rename_delete(self):
        cid = self.new_conversation()
        resp, events = self.send(cid, "Explain recursion")
        self.assertEqual(resp.status, 200)
        names = [e[0] for e in events]
        self.assertEqual(names[0], "start")
        self.assertIn("delta", names)
        self.assertEqual(names[-1], "done")
        self.assertEqual(events[0][1]["conversation"]["title"], "Explain recursion")
        streamed = "".join(d["text"] for n, d in events if n == "delta")
        final = events[-1][1]["assistant_message"]
        self.assertEqual(final["content"], streamed)
        self.assertEqual(final["status"], "complete")
        self.assertTrue(final["simulated"])

        status, data = self.json("GET", f"/api/conversations/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
        self.assertFalse(data["busy"])

        status, data = self.json(
            "PATCH", f"/api/conversations/{cid}", {"title": "  שם חדש "}
        )
        self.assertEqual((status, data["conversation"]["title"]), (200, "שם חדש"))

        status, data = self.json("GET", "/api/conversations")
        self.assertEqual([c["id"] for c in data["conversations"]], [cid])

        self.assertEqual(self.json("DELETE", f"/api/conversations/{cid}")[0], 200)
        self.assertEqual(self.json("GET", f"/api/conversations/{cid}")[0], 404)
        self.assertEqual(self.json("DELETE", f"/api/conversations/{cid}")[0], 404)

    def test_history_survives_server_restart(self):
        cid = self.new_conversation()
        self.send(cid, "keep this")
        self.stop()
        self.start(DemoProvider(delay_s=0))
        status, data = self.json("GET", f"/api/conversations/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual(data["messages"][0]["content"], "keep this")
        self.assertEqual(data["messages"][1]["status"], "complete")

    def test_status_reports_demo_mode(self):
        status, data = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["simulated"])
        self.assertEqual(data["provider"], "demo")
        self.assertNotIn("key", json.dumps(data).lower())

    def test_static_ui_has_security_headers(self):
        resp, body = self.request("GET", "/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<!doctype html>", body)
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(self.request("GET", "/static/../server.py")[0].status, 404)


class ValidationAndAccessTest(ServerTestCase):
    overrides = {"max_message_chars": 50, "rate_limit_per_minute": 3}

    def test_rejects_bad_input(self):
        cid = self.new_conversation()
        for body in [
            {},
            {"content": ""},
            {"content": "   "},
            {"content": 5},
            {"content": "x" * 51},
        ]:
            resp, _ = self.request("POST", f"/api/conversations/{cid}/messages", body)
            self.assertEqual(resp.status, 400, body)
        resp, _ = self.request(
            "POST",
            f"/api/conversations/{cid}/messages",
            raw=b"not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)
        resp, _ = self.request(
            "POST",
            f"/api/conversations/{cid}/messages",
            raw=b'{"content":"hi"}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status, 400)
        self.assertEqual(
            self.json("PATCH", f"/api/conversations/{cid}", {"title": ""})[0], 400
        )
        self.assertEqual(self.json("GET", "/api/conversations/not-an-id")[0], 400)
        missing = "0" * 32
        self.assertEqual(
            self.request(
                "POST", f"/api/conversations/{missing}/messages", {"content": "hi"}
            )[0].status,
            404,
        )

    def test_oversized_body_rejected_without_reading(self):
        cid = self.new_conversation()
        resp, _ = self.request(
            "POST",
            f"/api/conversations/{cid}/messages",
            raw=b"x" * 10_000,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    def test_rate_limit(self):
        cid = self.new_conversation()
        codes = [self.send(cid, f"m{i}")[0].status for i in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_csrf_and_host_checks(self):
        self.assertEqual(
            self.json("POST", "/api/conversations", {}, csrf=False)[0], 403
        )
        self.assertEqual(
            self.json(
                "POST",
                "/api/conversations",
                {},
                headers={"Origin": "https://evil.example"},
            )[0],
            403,
        )
        self.assertEqual(
            self.json(
                "POST",
                "/api/conversations",
                {},
                headers={"Origin": f"http://localhost:{self.port}"},
            )[0],
            201,
        )
        self.assertEqual(
            self.json("GET", "/api/conversations", headers={"Host": "evil.example"})[0],
            421,
        )
        self.assertEqual(
            self.json(
                "GET",
                "/api/conversations",
                headers={"Host": f"attacker.test:{self.port}"},
            )[0],
            421,
        )


class ProviderErrorFlowTest(ServerTestCase):
    provider = ScriptedProvider(
        error=ProviderError("overloaded", "Provider overloaded.")
    )

    def test_error_is_streamed_and_persisted_with_partial_text(self):
        cid = self.new_conversation()
        _, events = self.send(cid, "hello")
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["message"], "Provider overloaded.")
        _, data = self.json("GET", f"/api/conversations/{cid}")
        reply = data["messages"][1]
        self.assertEqual(reply["status"], "error")
        self.assertEqual(reply["content"], "Hi there")
        self.assertFalse(reply["simulated"])

    def test_live_failure_never_falls_back_to_demo(self):
        cid = self.new_conversation()
        _, events = self.send(cid, "hello")
        self.assertFalse(any("Demo mode" in json.dumps(d) for _, d in events))
        reply = events[-1][1]["assistant_message"]
        self.assertEqual(reply["provider"], "scripted")
        self.assertFalse(reply["simulated"])
        self.assertNotIn("simulated", reply["content"].lower())
        status, data = self.json("GET", "/api/status")
        self.assertEqual((data["provider"], data["simulated"]), ("scripted", False))

    def test_errored_reply_is_excluded_from_next_context(self):
        cid = self.new_conversation()
        self.send(cid, "first")
        self.send(cid, "second")
        turns = self.provider.calls[-1]
        self.assertEqual([t.role for t in turns], ["user", "user"])


class CancelFlowTest(ServerTestCase):
    def test_cancel_endpoint_stops_generation(self):
        gate = threading.Event()
        self.stop()
        self.start(ScriptedProvider(chunks=("one ", "two ", "three"), gate=gate))
        cid = self.new_conversation()
        result = {}
        t = threading.Thread(target=lambda: result.update(r=self.send(cid, "go")))
        t.start()
        for _ in range(100):
            if self.app.chat.is_busy(cid):
                break
            time.sleep(0.01)
        self.assertEqual(
            self.json(
                "POST", f"/api/conversations/{cid}/messages", {"content": "again"}
            )[0],
            409,
        )
        self.assertTrue(
            self.json("POST", f"/api/conversations/{cid}/cancel")[1]["cancelled"]
        )
        gate.set()
        t.join(5)
        events = result["r"][1]
        final = events[-1][1]["assistant_message"]
        self.assertEqual(final["status"], "cancelled")
        self.assertEqual(final["content"], "one ")


class ContextTest(unittest.TestCase):
    def msg(self, role, content, status="complete"):
        return Message(
            "x", "c", role, content, status, None, None, False, None, None, 0
        )

    def test_budget_keeps_newest_and_starts_with_user(self):
        history = [
            self.msg("user", "a" * 50),
            self.msg("assistant", "b" * 50),
            self.msg("user", "c" * 10),
            self.msg("assistant", "", "error"),
            self.msg("assistant", "partial", "cancelled"),
            self.msg("user", "d" * 10),
        ]
        turns = build_context(history, max_chars=80)
        self.assertEqual([t.content[0] for t in turns], ["c", "p", "d"])
        turns = build_context(history, max_chars=5)
        self.assertEqual([t.content for t in turns], ["d" * 10])  # newest always kept


if __name__ == "__main__":
    unittest.main()


class StopReasonFlowTest(ServerTestCase):
    def reply_for(self, end):
        self.stop()
        self.start(ScriptedProvider(end=end))
        cid = self.new_conversation()
        _, events = self.send(cid, "hello")
        self.assertEqual(events[-1][0], "done")
        return events[-1][1]["assistant_message"]

    def test_complete_reply_records_usage_and_served_model(self):
        reply = self.reply_for(StreamEnd("end_turn", 9))
        self.assertEqual(reply["status"], "complete")
        self.assertEqual(reply["response_model"], "served-model-7")
        self.assertEqual((reply["input_tokens"], reply["output_tokens"]), (21, 9))

    def test_token_limit_is_marked_incomplete(self):
        reply = self.reply_for(StreamEnd("max_tokens", 100))
        self.assertEqual(
            (reply["status"], reply["stop_reason"]), ("incomplete", "max_tokens")
        )
        self.assertEqual(reply["content"], "Hi there")

    def test_other_stop_reasons_are_incomplete(self):
        for reason in [
            "refusal",
            "model_context_window_exceeded",
            "pause_turn",
            "new_one",
        ]:
            self.assertEqual(
                self.reply_for(StreamEnd(reason))["status"], "incomplete", reason
            )
        self.assertEqual(
            self.reply_for(StreamEnd("stop_sequence"))["status"], "complete"
        )

    def test_incomplete_reply_stays_in_context(self):
        self.stop()
        provider = ScriptedProvider(end=StreamEnd("max_tokens"))
        self.start(provider)
        cid = self.new_conversation()
        self.send(cid, "one")
        self.send(cid, "two")
        self.assertEqual(
            [t.role for t in provider.calls[-1]], ["user", "assistant", "user"]
        )

    def test_malformed_content_length_on_create(self):
        resp, _ = self.request(
            "POST",
            "/api/conversations",
            raw=b"",
            headers={"Content-Length": "abc", "Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)


class ProviderClosedOnCancelTest(unittest.TestCase):
    def test_generator_closed_when_cancelled(self):
        import tempfile as _t

        from aiworkspace.chat import ChatService
        from aiworkspace.store import Store

        closed = []

        class Slow:
            name, model, simulated = "slow", "m", False

            def stream(self, system, turns, max_tokens, cancel, deadline):
                try:
                    yield TextDelta("a")
                    cancel.set()
                    yield TextDelta("b")
                    yield TextDelta("never")
                finally:
                    closed.append(True)

        with _t.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db")
            svc = ChatService(store, Slow(), 10, 1000, 30)
            cid = store.create_conversation("t").id
            sent = []
            svc.reply(cid, "hi", lambda e, d: sent.append((e, d)), lambda: None)
            self.assertEqual(closed, [True])
            final = sent[-1][1]["assistant_message"]
            self.assertEqual(final["status"], "cancelled")
            self.assertEqual(final["content"], "ab")
