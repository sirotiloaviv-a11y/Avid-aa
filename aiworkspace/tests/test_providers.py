"""Anthropic adapter against canned HTTP responses. These are mocked: they check
request shape and error mapping, not live-provider behaviour."""

import io
import json
import socket
import threading
import time
import unittest
import urllib.error
from email.message import Message as Headers

from aiworkspace.providers.anthropic import AnthropicProvider, iter_sse
from aiworkspace.providers.base import (
    Heartbeat,
    ProviderError,
    ResponseStart,
    StreamEnd,
    TextDelta,
    Turn,
)
from aiworkspace.providers.demo import DemoProvider

KEY = "sk-ant-test-not-real"


def sse(*events):
    out = []
    for name, payload in events:
        out.append(f"event: {name}\ndata: {json.dumps(payload)}\n\n")
    return "".join(out).encode("utf-8")


HAPPY = sse(
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-5",
                "usage": {"input_tokens": 12, "output_tokens": 1},
            },
        },
    ),
    # A thinking block (display omitted): never surfaced as text.
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "private reasoning"},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "sig"},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    ),
    ("ping", {"type": "ping"}),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": " שלום"},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
)


def http_error(status, body, headers=None):
    h = Headers()
    for k, v in (headers or {}).items():
        h[k] = v
    return urllib.error.HTTPError(
        "https://api.anthropic.com/v1/messages",
        status,
        "err",
        h,
        io.BytesIO(json.dumps(body).encode()),
    )


class FakeOpener:
    """Returns or raises the queued outcomes in order, recording requests."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(outcome)


def run(provider, cancel=None, timeout=30):
    cancel = cancel or threading.Event()
    events = list(
        provider.stream(
            "sys", [Turn("user", "hi")], 100, cancel, time.monotonic() + timeout
        )
    )
    return events


def provider_with(*outcomes, **kw):
    opener = FakeOpener(*outcomes)
    sleeps = []
    p = AnthropicProvider(
        KEY, "claude-opus-5", opener=opener, sleep=sleeps.append, **kw
    )
    return p, opener, sleeps


class AnthropicRequestTest(unittest.TestCase):
    def test_streams_text_and_stop_reason(self):
        p, opener, _ = provider_with(HAPPY)
        events = run(p)
        text = "".join(e.text for e in events if isinstance(e, TextDelta))
        self.assertEqual(text, "Hello שלום")  # thinking text is not included
        self.assertEqual(events[0], ResponseStart("claude-opus-5", 12))
        self.assertEqual(events[-1], StreamEnd("end_turn", 3))
        self.assertTrue(any(isinstance(e, Heartbeat) for e in events))

    def test_request_shape(self):
        p, opener, _ = provider_with(HAPPY)
        run(p)
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_method(), "POST")
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["x-api-key"], KEY)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["content-type"], "application/json")
        # Default request is the plain, non-beta Messages request.
        self.assertNotIn("anthropic-beta", headers)
        body = json.loads(req.data)
        self.assertEqual(
            body,
            {
                "model": "claude-opus-5",
                "max_tokens": 100,
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
                "system": "sys",
            },
        )

    def test_fallbacks_are_opt_in(self):
        p, opener, _ = provider_with(HAPPY, fallbacks="default")
        run(p)
        headers = {k.lower(): v for k, v in opener.requests[0].header_items()}
        self.assertEqual(headers["anthropic-beta"], "server-side-fallback-2026-07-01")
        self.assertEqual(json.loads(opener.requests[0].data)["fallbacks"], "default")

    def test_key_not_in_repr(self):
        p, _, _ = provider_with()
        self.assertNotIn(KEY, repr(p))

    def test_refusal_stop_reason_is_reported(self):
        body = sse(
            (
                "message_delta",
                {"type": "message_delta", "delta": {"stop_reason": "refusal"}},
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        p, _, _ = provider_with(body)
        self.assertEqual(run(p)[-1], StreamEnd("refusal"))

    def test_max_tokens_stop_reason_and_usage(self):
        body = HAPPY.replace(b'"end_turn"', b'"max_tokens"')
        p, _, _ = provider_with(body)
        self.assertEqual(run(p)[-1], StreamEnd("max_tokens", 3))


class AnthropicErrorTest(unittest.TestCase):
    def assertKind(self, exc_ctx, kind):
        self.assertEqual(exc_ctx.exception.kind, kind)
        self.assertNotIn(KEY, exc_ctx.exception.message)

    def test_auth_error_not_retried(self):
        err = http_error(
            401,
            {
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid x-api-key",
                },
            },
        )
        p, opener, _ = provider_with(err)
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "auth")
        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(len(opener.requests), 1)

    def test_not_found_includes_upstream_detail(self):
        err = http_error(
            404,
            {
                "type": "error",
                "error": {"type": "not_found_error", "message": "model: nope"},
            },
        )
        p, _, _ = provider_with(err)
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "not_found")
        self.assertIn("model: nope", ctx.exception.message)

    def test_rate_limit_retried_with_retry_after(self):
        err = http_error(
            429,
            {"type": "error", "error": {"type": "rate_limit_error"}},
            {"retry-after": "2"},
        )
        p, opener, sleeps = provider_with(err, HAPPY)
        events = run(p)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(events[-1], StreamEnd("end_turn", 3))

    def test_overloaded_gives_up_after_max_attempts(self):
        def overloaded():
            return http_error(
                529, {"type": "error", "error": {"type": "overloaded_error"}}
            )

        p, opener, sleeps = provider_with(overloaded(), overloaded(), overloaded())
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "overloaded")
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(len(sleeps), 2)

    def test_unparseable_error_body_uses_status(self):
        def bad_gateway():
            return urllib.error.HTTPError(
                "u", 502, "bad gateway", Headers(), io.BytesIO(b"<html>")
            )

        p, _, _ = provider_with(bad_gateway(), bad_gateway(), bad_gateway())
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "server")

    def test_ambiguous_network_error_not_retried(self):
        # The request may have reached the API; retrying could bill twice.
        p, opener, _ = provider_with(
            urllib.error.URLError(ConnectionResetError()), HAPPY
        )
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "network")
        self.assertEqual(len(opener.requests), 1)

    def test_unsent_request_is_retried(self):
        p, opener, _ = provider_with(
            urllib.error.URLError(socket.gaierror("dns")),
            urllib.error.URLError(ConnectionRefusedError()),
            HAPPY,
        )
        self.assertEqual(run(p)[-1], StreamEnd("end_turn", 3))
        self.assertEqual(len(opener.requests), 3)

    def test_timeout_not_retried(self):
        p, opener, _ = provider_with(socket.timeout("t"), HAPPY)
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "timeout")
        self.assertEqual(len(opener.requests), 1)

    def test_retries_are_bounded_and_configurable(self):
        def overloaded():
            return http_error(
                529, {"type": "error", "error": {"type": "overloaded_error"}}
            )

        p, opener, _ = provider_with(*(overloaded() for _ in range(5)), max_retries=0)
        with self.assertRaises(ProviderError):
            run(p)
        self.assertEqual(len(opener.requests), 1)
        with self.assertRaises(ValueError):
            AnthropicProvider(KEY, "m", max_retries=4)

    def test_mid_stream_error_event(self):
        body = HAPPY.rsplit(b"event: content_block_stop", 1)[0] + sse(
            (
                "error",
                {
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "Overloaded"},
                },
            )
        )
        p, opener, _ = provider_with(body, HAPPY)
        events = []
        with self.assertRaises(ProviderError) as ctx:
            for ev in p.stream(
                "", [Turn("user", "hi")], 100, threading.Event(), time.monotonic() + 9
            ):
                events.append(ev)
        self.assertKind(ctx, "overloaded")
        # Text before the error was delivered; the request is not repeated.
        self.assertIn(TextDelta("Hello"), events)
        self.assertEqual(len(opener.requests), 1)

    def test_malformed_event_data(self):
        p, _, _ = provider_with(b"event: content_block_delta\ndata: {not json\n\n")
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "protocol")

    def test_stream_that_ends_early(self):
        p, _, _ = provider_with(HAPPY.split(b"event: message_stop")[0])
        with self.assertRaises(ProviderError) as ctx:
            run(p)
        self.assertKind(ctx, "protocol")

    def test_deadline_already_passed(self):
        p, opener, _ = provider_with(HAPPY)
        with self.assertRaises(ProviderError) as ctx:
            run(p, timeout=-1)
        self.assertKind(ctx, "timeout")
        self.assertEqual(opener.requests, [])

    def test_cancel_stops_stream(self):
        p, _, _ = provider_with(HAPPY)
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(run(p, cancel=cancel), [StreamEnd("cancelled")])


class SSEParserTest(unittest.TestCase):
    def test_comments_crlf_and_multiline_data(self):
        raw = b": comment\r\nevent: x\r\ndata: a\r\ndata: b\r\n\r\ndata:c\n\n"
        self.assertEqual(list(iter_sse(io.BytesIO(raw))), [("x", "a\nb"), ("", "c")])


class DemoProviderTest(unittest.TestCase):
    def stream(self, text, cancel=None):
        p = DemoProvider(delay_s=0)
        return list(
            p.stream(
                "",
                [Turn("user", text)],
                100,
                cancel or threading.Event(),
                time.monotonic() + 5,
            )
        )

    def test_is_labelled_simulated(self):
        self.assertTrue(DemoProvider.simulated)
        text = "".join(e.text for e in self.stream("hello") if isinstance(e, TextDelta))
        self.assertIn("simulated", text)
        he = "".join(e.text for e in self.stream("שלום") if isinstance(e, TextDelta))
        self.assertIn("מדומה", he)

    def test_error_trigger(self):
        with self.assertRaises(ProviderError):
            self.stream("/demo-error")

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(self.stream("hello", cancel), [StreamEnd("cancelled")])


if __name__ == "__main__":
    unittest.main()


class LocalHTTPTest(unittest.TestCase):
    """The adapter's real urllib path against a local stand-in server (still mocked)."""

    def test_streams_over_real_socket(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        seen = {}

        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen["path"] = self.path
                seen["key"] = self.headers.get("x-api-key")
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(HAPPY)

        srv = HTTPServer(("127.0.0.1", 0), Fake)
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            p = AnthropicProvider(
                KEY, "m", base_url=f"http://127.0.0.1:{srv.server_address[1]}"
            )
            events = run(p)
        finally:
            t.join(5)
            srv.server_close()
        text = "".join(e.text for e in events if isinstance(e, TextDelta))
        self.assertEqual(text, "Hello שלום")
        self.assertEqual(seen, {"path": "/v1/messages", "key": KEY})
