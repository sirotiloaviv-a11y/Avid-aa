"""Minimal RFC 6455 WebSocket client on the standard library.

Enough for market-data streams: text/binary messages, fragmentation,
ping/pong, close. ``recv(timeout)`` returns ``None`` on timeout without
losing a partially received frame (bytes stay buffered), so a caller can
interleave heartbeats with reads on one thread.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 16 * 1024 * 1024

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WebSocketError(ConnectionError):
    """Handshake failure, protocol violation, or the peer closed the stream."""


class WebSocket:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()
        self._fragments: list[bytes] = []
        self._fragment_op = OP_TEXT
        self.closed = False

    # ---------------------------------------------------------- handshake
    @classmethod
    def connect(cls, url: str, *, timeout: float = 10.0, headers: dict[str, str] | None = None) -> WebSocket:
        parts = urlsplit(url)
        if parts.scheme not in ("ws", "wss"):
            raise WebSocketError(f"not a websocket URL: {url}")
        secure = parts.scheme == "wss"
        host = parts.hostname or ""
        port = parts.port or (443 if secure else 80)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        raw = socket.create_connection((host, port), timeout=timeout)
        sock: socket.socket = raw
        try:
            if secure:
                sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            key = base64.b64encode(os.urandom(16)).decode()
            host_header = host if parts.port is None else f"{host}:{port}"
            lines = [
                f"GET {path} HTTP/1.1",
                f"Host: {host_header}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                *(f"{k}: {v}" for k, v in (headers or {}).items()),
            ]
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            ws = cls(sock)
            ws._handshake_response(key, timeout)
            return ws
        except BaseException:
            sock.close()
            raise

    def _handshake_response(self, key: str, timeout: float) -> None:
        self._sock.settimeout(timeout)
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            self._buf.extend(chunk)
            if len(self._buf) > 65536:
                raise WebSocketError("handshake response too large")
        head, _, rest = bytes(self._buf).partition(b"\r\n\r\n")
        self._buf = bytearray(rest)
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in f"{status_line} ":
            raise WebSocketError(f"handshake refused: {status_line}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in header_lines)}
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()  # noqa: S324
        if headers.get("sec-websocket-accept") != expected:
            raise WebSocketError("handshake failed: bad Sec-WebSocket-Accept")

    # ------------------------------------------------------------- frames
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise WebSocketError("websocket is closed")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(OP_TEXT, text.encode("utf-8"))

    def ping(self, payload: bytes = b"") -> None:
        self._send_frame(OP_PING, payload)

    def _parse_frame(self) -> tuple[bool, int, bytes] | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        fin, opcode = bool(buf[0] & 0x80), buf[0] & 0x0F
        masked, length = bool(buf[1] & 0x80), buf[1] & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                return None
            length = struct.unpack("!H", buf[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            length = struct.unpack("!Q", buf[2:10])[0]
            offset = 10
        if length > MAX_MESSAGE:
            raise WebSocketError(f"frame of {length} bytes exceeds limit")
        mask = b""
        if masked:
            if len(buf) < offset + 4:
                return None
            mask = bytes(buf[offset:offset + 4])
            offset += 4
        if len(buf) < offset + length:
            return None
        payload = bytes(buf[offset:offset + length])
        del buf[:offset + length]
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv(self, timeout: float | None = None) -> str | None:
        """Next complete message, or None if ``timeout`` passes first."""
        while True:
            frame = self._parse_frame()
            if frame is None:
                self._sock.settimeout(timeout)
                try:
                    chunk = self._sock.recv(65536)
                except (socket.timeout, TimeoutError):
                    return None
                if not chunk:
                    self.closed = True
                    raise WebSocketError("connection closed by peer")
                self._buf.extend(chunk)
                continue
            fin, opcode, payload = frame
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                self._reply_close()
                raise WebSocketError(f"server closed the stream (code {code})")
            if opcode in (OP_TEXT, OP_BINARY):
                self._fragments = [payload]
                self._fragment_op = opcode
            elif opcode == OP_CONT:
                self._fragments.append(payload)
            else:
                raise WebSocketError(f"unknown opcode {opcode}")
            if fin:
                message = b"".join(self._fragments)
                self._fragments = []
                return message.decode("utf-8", errors="replace")

    def _reply_close(self) -> None:
        if not self.closed:
            try:
                self._send_frame(OP_CLOSE, struct.pack("!H", 1000))
            except OSError:
                pass
        self.closed = True

    def close(self) -> None:
        self._reply_close()
        try:
            self._sock.close()
        except OSError:
            pass
