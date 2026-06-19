"""Generic Icecast2 source-client.

Pushes audio chunks to an Icecast2 server using the PUT-based
HTTP-source protocol. Works with self-hosted Icecast as well as
the Broadcastify ingest mounts (handled by :mod:`streaming.broadcastify`).

Usage::

    push = IcecastPusher(
        host="icecast.example.com", port=8000,
        mount="/scanner.mp3", password="hackme",
        content_type="audio/mpeg",
    )
    push.start()
    push.feed(encoded_chunk_bytes)
    ...
    push.stop()

The pusher runs on a background thread + uses a queue between the
main thread (which calls :meth:`feed`) and the network sender. Chunks
queue up to ``queue_max`` items before the oldest is dropped (so the
push never holds back the encoder).

Auth is HTTP basic with the username ``source`` and the supplied
password (Icecast2's documented source-client convention).
"""

from __future__ import annotations

import base64
import logging
import queue
import socket
import ssl
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class IcecastPusher:
    def __init__(
        self,
        host: str,
        port: int,
        mount: str,
        password: str,
        username: str = "source",
        content_type: str = "audio/mpeg",
        use_tls: bool = False,
        bitrate_kbps: int = 64,
        queue_max: int = 64,
        connect_timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.mount = mount if mount.startswith("/") else f"/{mount}"
        self.password = password
        self.username = username
        self.content_type = content_type
        self.use_tls = use_tls
        self.bitrate_kbps = bitrate_kbps
        self._queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=queue_max)
        self._thread: Optional[threading.Thread] = None
        self._stopping = False
        self._connect_timeout = connect_timeout
        self._status: str = "idle"
        self._last_error: Optional[str] = None
        self._listeners_at_last_status: Optional[int] = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping = False
        self._status = "connecting"
        self._thread = threading.Thread(
            target=self._run, name=f"icecast-push-{self.host}", daemon=True
        )
        self._thread.start()

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            # Drop oldest, push newest
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                pass

    def stop(self, timeout: float = 3.0) -> None:
        self._stopping = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._status = "stopped"

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                self._connect_and_send()
                backoff = 1.0
            except Exception as exc:
                self._last_error = str(exc)
                self._status = "error"
                logger.warning("Icecast push failed: %s", exc)
                if self._stopping:
                    break
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _connect_and_send(self) -> None:
        sock = socket.create_connection(
            (self.host, self.port), timeout=self._connect_timeout
        )
        try:
            if self.use_tls:
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=self.host)

            auth = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            request = (
                f"PUT {self.mount} HTTP/1.1\r\n"
                f"Host: {self.host}\r\n"
                f"Authorization: Basic {auth}\r\n"
                f"User-Agent: ScannerManager/1.0\r\n"
                f"Content-Type: {self.content_type}\r\n"
                f"ice-name: Scanner Manager\r\n"
                f"ice-bitrate: {self.bitrate_kbps}\r\n"
                f"ice-public: 0\r\n"
                f"Expect: 100-continue\r\n"
                f"\r\n"
            )
            sock.sendall(request.encode("ascii"))
            # Wait for the 100/200 response line; Icecast doesn't always
            # send 100-continue, so accept either.
            sock.settimeout(self._connect_timeout)
            try:
                head = sock.recv(2048)
                if b"401" in head or b"403" in head:
                    raise RuntimeError("Icecast rejected auth (401/403)")
            except socket.timeout:
                pass

            self._status = "streaming"
            sock.settimeout(None)
            while not self._stopping:
                chunk = self._queue.get()
                if chunk is None or self._stopping:
                    break
                try:
                    sock.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    raise RuntimeError(f"socket lost: {exc}") from exc
        finally:
            try:
                sock.close()
            except Exception:
                pass
            if not self._stopping:
                self._status = "reconnecting"
