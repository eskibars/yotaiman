"""A minimal RFC 6455 WebSocket client built on the standard library.

Only what the CDP bootstrap needs: a client-side handshake, masked text
frames, and reassembly of continuation frames.  Keeping this in-tree means
``python -m yoto.auth bootstrap`` has no third-party dependencies.
"""

from __future__ import annotations

import base64
import os
import socket
import struct
from typing import Any
from urllib.parse import urlparse

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketError(RuntimeError):
    """Raised when the socket handshake or frame stream goes wrong."""


class WebSocket:
    """A blocking client WebSocket."""

    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise WebSocketError(f"unsupported scheme: {parsed.scheme}")
        host = parsed.hostname or "localhost"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buffer = b""

        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(handshake.encode())

        header = self._read_until(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0].decode(errors="replace")
        if "101" not in status_line:
            raise WebSocketError(f"handshake failed: {status_line}")

    # ------------------------------------------------------------------
    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            self._buffer += chunk
        head, _, rest = self._buffer.partition(marker)
        self._buffer = rest
        return head + marker

    def _read_exactly(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(max(65536, count - len(self._buffer)))
            if not chunk:
                raise WebSocketError("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _read_frame(self) -> tuple[int, bool, bytes]:
        first, second = self._read_exactly(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._read_exactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exactly(8))[0]

        mask = self._read_exactly(4) if masked else b""
        payload = self._read_exactly(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, fin, payload

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    # ------------------------------------------------------------------
    def send(self, message: str) -> None:
        """Send a text message."""
        self._send_frame(OP_TEXT, message.encode())

    def recv(self) -> str:
        """Receive the next text message, reassembling fragments."""
        chunks: list[bytes] = []
        first_opcode: int | None = None
        while True:
            opcode, fin, payload = self._read_frame()
            if opcode == OP_CLOSE:
                raise WebSocketError("server closed the connection")
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode != OP_CONTINUATION:
                first_opcode = opcode
                chunks = []
            chunks.append(payload)
            if fin:
                data = b"".join(chunks)
                if first_opcode == OP_BINARY:
                    return data.decode(errors="replace")
                return data.decode(errors="replace")

    def send_json(self, payload: Any) -> None:
        """Send a JSON-serialisable payload as a text frame."""
        import json

        self.send(json.dumps(payload))

    def recv_json(self) -> Any:
        """Receive and decode the next JSON message."""
        import json

        return json.loads(self.recv())

    def close(self) -> None:
        """Close the socket."""
        try:
            self._send_frame(OP_CLOSE, b"")
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self) -> "WebSocket":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
