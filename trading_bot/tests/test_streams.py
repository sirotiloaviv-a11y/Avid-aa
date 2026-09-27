from __future__ import annotations

import base64
import hashlib
import socket
import struct
import threading
import time
import unittest
from typing import Callable

from trading_bot.brokers.streams import ReconnectingStream
from trading_bot.utils.websocket import GUID, WebSocket, WebSocketError


def frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(payload) < 126:
        head += bytes([len(payload)])
    else:
        head += bytes([126]) + struct.pack("!H", len(payload))
    return head + payload


def read_client_frame(conn: socket.socket) -> tuple[int, bytes]:
    b1, b2 = conn.recv(2, socket.MSG_WAITALL)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2, socket.MSG_WAITALL))[0]
    assert b2 & 0x80, "client frames must be masked"
    mask = conn.recv(4, socket.MSG_WAITALL)
    data = conn.recv(length, socket.MSG_WAITALL) if length else b""
    return b1 & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class LocalServer:
    """Tiny single-connection WebSocket server for tests."""

    def __init__(self, script: Callable[[socket.socket], None], *, accept_key: bool = True) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.script = script
        self.accept_key = accept_key
        self.received: list[tuple[int, bytes]] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.sock.accept()
        with conn:
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(1024)
            key = next(line.split(":", 1)[1].strip() for line in request.decode().split("\r\n")
                       if line.lower().startswith("sec-websocket-key"))
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            if not self.accept_key:
                accept = "wrong"
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
            try:
                self.script(conn)
            except OSError:
                pass

    def close(self) -> None:
        self.sock.close()


class WebSocketClientTests(unittest.TestCase):
    def test_messages_fragments_ping_and_close(self) -> None:
        server_holder: list[LocalServer] = []

        def script(conn: socket.socket) -> None:
            conn.sendall(frame(0x1, b"hello"))
            conn.sendall(frame(0x9, b"hb"))                       # ping -> client must pong
            server_holder[0].received.append(read_client_frame(conn))
            conn.sendall(frame(0x1, b"frag", fin=False) + frame(0x0, b"ment"))
            big = b"x" * 70000
            conn.sendall(bytes([0x81, 127]) + struct.pack("!Q", len(big)) + big)
            server_holder[0].received.append(read_client_frame(conn))  # client text
            conn.sendall(frame(0x8, struct.pack("!H", 1000)))

        server = LocalServer(script)
        server_holder.append(server)
        ws = WebSocket.connect(f"ws://127.0.0.1:{server.port}/stream")
        try:
            self.assertEqual(ws.recv(timeout=2), "hello")
            self.assertEqual(ws.recv(timeout=2), "fragment")
            self.assertEqual(len(ws.recv(timeout=2) or ""), 70000)
            ws.send_text("subscribe")
            with self.assertRaises(WebSocketError):
                ws.recv(timeout=2)
        finally:
            ws.close()
            server.thread.join(2)
            server.close()
        self.assertEqual(server.received[0], (0xA, b"hb"))
        self.assertEqual(server.received[1], (0x1, b"subscribe"))

    def test_timeout_keeps_partial_frame(self) -> None:
        release = threading.Event()

        def script(conn: socket.socket) -> None:
            data = frame(0x1, b"split-message")
            conn.sendall(data[:5])
            release.wait(2)
            conn.sendall(data[5:])
            time.sleep(0.2)

        server = LocalServer(script)
        ws = WebSocket.connect(f"ws://127.0.0.1:{server.port}/")
        try:
            self.assertIsNone(ws.recv(timeout=0.2))
            release.set()
            self.assertEqual(ws.recv(timeout=2), "split-message")
        finally:
            ws.close()
            server.close()

    def test_bad_handshake(self) -> None:
        def silent(_conn: socket.socket) -> None:
            return None

        server = LocalServer(silent, accept_key=False)
        with self.assertRaises(WebSocketError):
            WebSocket.connect(f"ws://127.0.0.1:{server.port}/")
        server.close()
        with self.assertRaises(WebSocketError):
            WebSocket.connect("http://example.com/")


class FakeSocket:
    def __init__(self, messages: list[str | None], fail_after: bool = True) -> None:
        self.messages = messages
        self.fail_after = fail_after
        self.sent: list[str] = []
        self.closed = False

    def send_text(self, text: str) -> None:
        self.sent.append(text)

    def recv(self, timeout: float | None = None) -> str | None:
        if self.messages:
            return self.messages.pop(0)
        if self.fail_after:
            raise ConnectionError("dropped")
        time.sleep(0.01)
        return None

    def close(self) -> None:
        self.closed = True


class ReconnectingStreamTests(unittest.TestCase):
    def test_reconnects_resubscribes_and_delivers(self) -> None:
        sockets = [FakeSocket(["a", "b"]), FakeSocket(["c"], fail_after=False)]
        attempts: list[int] = []
        received: list[str] = []
        done = threading.Event()

        def connect() -> FakeSocket:
            attempts.append(1)
            if len(attempts) == 2:
                raise OSError("refused")  # one failed connect in between
            return sockets.pop(0)

        def on_message(message: str, _ws: object) -> None:
            received.append(message)
            if message == "c":
                done.set()

        stream = ReconnectingStream("t", connect, on_message,  # type: ignore[arg-type]
                                    on_open=lambda ws: ws.send_text("subscribe"),
                                    backoff_initial=0.01, backoff_max=0.05)
        stream.start()
        self.assertTrue(done.wait(3))
        stream.stop()
        self.assertEqual(received, ["a", "b", "c"])
        self.assertEqual(len(attempts), 3)
        self.assertGreaterEqual(stream.reconnects, 2)

    def test_silence_triggers_reconnect_and_heartbeats_are_sent(self) -> None:
        first = FakeSocket([], fail_after=False)
        second = FakeSocket(["x"], fail_after=False)
        pool = [first, second]
        got = threading.Event()
        stream = ReconnectingStream("t", lambda: pool.pop(0), lambda m, _w: got.set(),  # type: ignore[arg-type,misc]
                                    heartbeat=lambda ws: ws.send_text("ping"), heartbeat_interval=0.05,
                                    silence_timeout=0.2, backoff_initial=0.01)
        stream.start()
        self.assertTrue(got.wait(3))
        stream.stop()
        self.assertTrue(first.closed)
        self.assertIn("ping", first.sent)


if __name__ == "__main__":
    unittest.main()
