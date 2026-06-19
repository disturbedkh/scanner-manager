"""Tests for ``streaming.icecast`` with mocked sockets."""

from __future__ import annotations

import socket
import threading
import time
from typing import List, Optional

import pytest

from streaming.icecast import IcecastPusher

TEST_ICE_SECRET = "x"
TEST_ICE_SECRET_BAD = "bad"
TEST_ICE_SECRET_LIVE = "secret"
TEST_BF_SECRET = "secret"


class _FakeSocket:
    """Minimal socket stand-in for IcecastPusher worker thread."""

    def __init__(
        self,
        *,
        head: bytes = b"HTTP/1.1 200 OK\r\n\r\n",
        recv_timeout: bool = False,
    ) -> None:
        self.sent: List[bytes] = []
        self._head = head
        self._recv_calls = 0
        self._recv_timeout = recv_timeout
        self.closed = False
        self._timeout: Optional[float] = None

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:  # noqa: ARG002
        self._recv_calls += 1
        if self._recv_calls == 1:
            if self._recv_timeout:
                raise socket.timeout("simulated timeout on first recv")
            return self._head
        time.sleep(0.05)
        return b""

    def settimeout(self, value: Optional[float]) -> None:
        self._timeout = value

    def close(self) -> None:
        self.closed = True


def _wait_for_status(
    pusher: IcecastPusher, expected: str, timeout: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pusher.status == expected:
            return
        time.sleep(0.02)
    pytest.fail(f"status never reached {expected!r}; last={pusher.status!r}")


def test_mount_normalized_with_leading_slash() -> None:
    push = IcecastPusher(
        host="localhost", port=8000, mount="scanner.mp3", password=TEST_ICE_SECRET
    )
    assert push.mount == "/scanner.mp3"


def test_mount_keeps_existing_slash() -> None:
    push = IcecastPusher(
        host="localhost", port=8000, mount="/live", password=TEST_ICE_SECRET
    )
    assert push.mount == "/live"


def test_feed_ignores_empty_chunk() -> None:
    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=4
    )
    push.feed(b"")
    assert push._queue.empty()


def test_start_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSocket()
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=8
    )
    push.start()
    thread1 = push._thread
    push.start()
    assert push._thread is thread1
    push.stop(timeout=1.0)


def test_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSocket()
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=8
    )
    push.start()
    _wait_for_status(push, "streaming", timeout=2.0)
    push.stop(timeout=1.0)
    assert push.status == "stopped"
    push.stop(timeout=0.5)
    assert push.status == "stopped"


def test_queue_full_drops_oldest() -> None:
    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=2
    )
    push.feed(b"first")
    push.feed(b"second")
    push.feed(b"third")
    remaining = []
    while not push._queue.empty():
        remaining.append(push._queue.get_nowait())
    assert remaining == [b"second", b"third"]


def test_successful_stream_sends_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSocket()
    created: List[_FakeSocket] = []

    def _connect(*_args, **_kwargs) -> _FakeSocket:
        created.append(fake)
        return fake

    monkeypatch.setattr("streaming.icecast.socket.create_connection", _connect)
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="ice.example", port=8000, mount="/live", password=TEST_ICE_SECRET_LIVE, queue_max=8
    )
    push.start()
    _wait_for_status(push, "streaming", timeout=2.0)

    push.feed(b"audio-bytes")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if any(b"audio-bytes" in chunk for chunk in fake.sent):
            break
        time.sleep(0.02)
    else:
        pytest.fail("encoded chunk never reached mock socket")

    request = fake.sent[0].decode("ascii")
    assert "PUT /live HTTP/1.1" in request
    assert "Authorization: Basic" in request
    push.stop(timeout=1.0)
    assert fake.closed


def test_auth_failure_records_error_and_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection",
        lambda *a, **k: _FakeSocket(head=b"HTTP/1.1 401 Unauthorized\r\n\r\n"),
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET_BAD, queue_max=4
    )
    push.start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        err = push.last_error or ""
        if "401" in err or "auth" in err.lower():
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"expected auth error; last_error={push.last_error!r}")
    push.stop(timeout=1.0)


def test_recv_timeout_on_first_head_is_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Icecast may not answer 100-continue; timeout on first recv is OK."""
    fake = _FakeSocket(recv_timeout=True)
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=4
    )
    push.start()
    _wait_for_status(push, "streaming", timeout=2.0)
    push.stop(timeout=1.0)


def test_broadcastify_pusher_uses_defaults() -> None:
    from streaming.broadcastify import (
        DEFAULT_BROADCASTIFY_HOST,
        DEFAULT_BROADCASTIFY_PORT,
        BroadcastifyPusher,
    )

    pusher = BroadcastifyPusher(mount="/12345", password=TEST_BF_SECRET)
    assert pusher.host == DEFAULT_BROADCASTIFY_HOST
    assert pusher.port == DEFAULT_BROADCASTIFY_PORT
    assert pusher.mount == "/12345"


def test_feed_handles_race_when_queue_stays_full() -> None:
    import queue as stdlib_queue

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=1
    )

    class _RaceQueue(stdlib_queue.Queue):
        def get_nowait(self):
            raise stdlib_queue.Empty()

    push._queue = _RaceQueue(maxsize=1)
    push._queue.put_nowait(b"old")
    push.feed(b"new")
    assert push._queue.qsize() == 1


def test_stop_when_queue_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSocket()
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=1
    )
    push.feed(b"only")
    push.start()
    push.stop(timeout=1.0)
    assert push.status == "stopped"


def test_tls_wrap_is_used_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSocket()
    wrapped = []

    class _FakeCtx:
        def wrap_socket(self, sock, server_hostname=None):
            wrapped.append(server_hostname)
            return fake

    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.ssl.SSLContext", lambda *_a, **_k: _FakeCtx())
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="tls.example",
        port=443,
        mount="/x",
        password=TEST_ICE_SECRET,
        use_tls=True,
        queue_max=4,
    )
    push.start()
    _wait_for_status(push, "streaming", timeout=2.0)
    assert wrapped == ["tls.example"]
    push.stop(timeout=1.0)


def test_socket_loss_during_send_sets_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FlakySocket(_FakeSocket):
        def sendall(self, data: bytes) -> None:
            if b"HTTP/1.1" not in data:
                raise BrokenPipeError("gone")
            super().sendall(data)

    fake = _FlakySocket()
    monkeypatch.setattr(
        "streaming.icecast.socket.create_connection", lambda *a, **k: fake
    )
    monkeypatch.setattr("streaming.icecast.time.sleep", lambda _s: None)

    push = IcecastPusher(
        host="localhost", port=8000, mount="/x", password=TEST_ICE_SECRET, queue_max=4
    )
    push.start()
    _wait_for_status(push, "streaming", timeout=2.0)
    push.feed(b"chunk")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if push.last_error and "socket lost" in push.last_error:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"expected socket lost error; last_error={push.last_error!r}")
    push.stop(timeout=1.0)
