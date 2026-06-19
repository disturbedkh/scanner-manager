"""Tests for ``streaming.server`` using FastAPI's TestClient."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from streaming.server import StreamingServer  # noqa: E402


class _FakeEncoder:
    mime_type = "audio/mpeg"


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _attach_loop(server: StreamingServer) -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    runner = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    runner.start()
    server._loop = loop
    return loop, runner


def _stop_loop(loop: asyncio.AbstractEventLoop, runner: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    runner.join(timeout=2.0)
    loop.close()


def test_health_endpoint_returns_ok() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "audio_listeners" in body


def test_root_lists_endpoints() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "/audio" in body["endpoints"]["audio"]


def test_viewer_returns_html() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    response = client.get("/viewer")
    assert response.status_code == 200
    assert "<audio" in response.text
    assert "Scanner Manager" in response.text


def test_websocket_endpoint_accepts_connections() -> None:
    """Smoke test: a client can open the /telemetry websocket without crashing.

    The full end-to-end push test (open WS, push from another thread,
    receive) requires a real uvicorn server; that's covered in the
    Phase 6 integration tests. Here we just verify the handler accepts
    the upgrade.
    """
    server = StreamingServer()
    client = TestClient(server.app)
    with client.websocket_connect("/telemetry") as ws:
        # Subscriber count should be at least 1 while we're inside the ctx
        assert server.listener_counts()["telemetry"] >= 1
        ws.close()


def test_push_helpers_are_safe_when_loop_missing() -> None:
    """Calling push_audio_chunk / push_telemetry before starting the
    server must NOT raise - the streaming dock shouldn't have to
    guard every call."""
    server = StreamingServer()
    server.push_audio_chunk(b"some bytes")
    server.push_telemetry({"kind": "gsi", "mode": "Scan"})
    server.push_audio_chunk(b"")
    # No assertion needed - test passes if no exception


def test_listener_counts_start_at_zero() -> None:
    server = StreamingServer()
    assert server.listener_counts() == {"audio": 0, "telemetry": 0}


def test_set_encoder_changes_audio_mime_type() -> None:
    server = StreamingServer()
    server.set_encoder(_FakeEncoder())
    assert server._encoder is not None
    assert server._encoder.mime_type == "audio/mpeg"


def test_default_audio_mime_is_wav_without_encoder() -> None:
    server = StreamingServer()
    assert server._encoder is None


def test_push_audio_chunk_reaches_subscriber_queue() -> None:
    server = StreamingServer()
    loop, runner = _attach_loop(server)
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
    server._audio_subscribers.add(q)

    server.push_audio_chunk(b"chunk-1")
    future = asyncio.run_coroutine_threadsafe(q.get(), loop)
    assert future.result(timeout=2.0) == b"chunk-1"
    _stop_loop(loop, runner)


def test_push_telemetry_reaches_subscriber_queue() -> None:
    server = StreamingServer()
    loop, runner = _attach_loop(server)
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=64)
    server._telemetry_subscribers.add(q)

    payload = {"kind": "gsi", "mode": "Scan"}
    server.push_telemetry(payload)
    future = asyncio.run_coroutine_threadsafe(q.get(), loop)
    assert future.result(timeout=2.0) == payload
    _stop_loop(loop, runner)


def test_put_or_drop_replaces_oldest_when_queue_full() -> None:
    loop = asyncio.new_event_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    q.put_nowait(b"old")
    StreamingServer._put_or_drop(q, b"new")
    loop.run_until_complete(asyncio.sleep(0))
    assert loop.run_until_complete(q.get()) == b"new"
    loop.close()


def test_safe_put_swallows_loop_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    server = StreamingServer()

    class _BrokenLoop:
        def call_soon_threadsafe(self, *_args, **_kwargs) -> None:
            raise RuntimeError("loop gone")

    server._loop = _BrokenLoop()
    server.push_audio_chunk(b"data")


def test_websocket_receives_pushed_telemetry() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    with client.websocket_connect("/telemetry") as ws:
        assert server.listener_counts()["telemetry"] == 1
        q = next(iter(server._telemetry_subscribers))
        StreamingServer._put_or_drop(q, {"kind": "gsi", "mode": "Hold"})
        msg = ws.receive_json()
        assert msg["kind"] == "gsi"
        assert msg["mode"] == "Hold"


def test_telemetry_subscriber_removed_after_websocket_close() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    with client.websocket_connect("/telemetry"):
        assert server.listener_counts()["telemetry"] == 1
    assert server.listener_counts()["telemetry"] == 0


def test_telemetry_websocket_stops_when_none_sent() -> None:
    server = StreamingServer()
    client = TestClient(server.app)
    with client.websocket_connect("/telemetry") as ws:
        q = next(iter(server._telemetry_subscribers))
        StreamingServer._put_or_drop(q, {"kind": "gsi", "mode": "Scan"})
        assert ws.receive_json()["mode"] == "Scan"
        StreamingServer._put_or_drop(q, None)
        ws.close()


def test_stop_noop_when_never_started() -> None:
    server = StreamingServer()
    server.stop()
    assert server.is_running is False


def test_start_in_thread_and_stop(monkeypatch) -> None:
    pytest.importorskip("uvicorn")

    class _FakeUvicornServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            while not self.should_exit:
                await asyncio.sleep(0.01)

    class _FakeConfig:
        def __init__(self, app, host, port, log_level, access_log):
            self.app = app
            self.host = host
            self.port = port

    monkeypatch.setattr("uvicorn.Config", _FakeConfig)
    monkeypatch.setattr("uvicorn.Server", _FakeUvicornServer)

    server = StreamingServer(host="127.0.0.1", port=18766)
    server.start_in_thread()
    import time

    deadline = time.time() + 2.0
    while server._loop is None and time.time() < deadline:
        time.sleep(0.01)
    assert server.is_running
    server.stop(timeout=2.0)
    assert not server.is_running


def test_push_telemetry_with_no_subscribers() -> None:
    server = StreamingServer()
    loop, runner = _attach_loop(server)
    server.push_telemetry({"kind": "gsi"})
    _stop_loop(loop, runner)


async def _collect_audio_response(server: StreamingServer):
    for route in server.app.routes:
        if getattr(route, "path", None) == "/audio":
            return await route.endpoint()
    raise AssertionError("/audio route not found")


def test_audio_endpoint_streams_pushed_chunks() -> None:
    import asyncio

    server = StreamingServer()
    server.set_encoder(_FakeEncoder())

    async def _run() -> None:
        response = await _collect_audio_response(server)
        assert response.media_type == "audio/mpeg"
        queue = next(iter(server._audio_subscribers))
        queue.put_nowait(b"audio-chunk")
        queue.put_nowait(None)
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == [b"audio-chunk"]
        assert server.listener_counts()["audio"] == 0

    asyncio.run(_run())


def test_audio_endpoint_uses_wav_mime_without_encoder() -> None:
    import asyncio

    server = StreamingServer()

    async def _run() -> None:
        response = await _collect_audio_response(server)
        assert response.media_type == "audio/wav"
        queue = next(iter(server._audio_subscribers))
        queue.put_nowait(None)
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == []

    asyncio.run(_run())


def test_start_in_thread_without_uvicorn_raises() -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("no uvicorn")
        return real_import(name, *args, **kwargs)

    server = StreamingServer()
    with pytest.raises(RuntimeError, match="uvicorn not installed"):
        import builtins as bi

        old = bi.__import__
        bi.__import__ = _fake_import
        try:
            server.start_in_thread()
        finally:
            bi.__import__ = old


def test_put_or_drop_get_nowait_failure(monkeypatch) -> None:
    loop = asyncio.new_event_loop()

    class _BadQueue(asyncio.Queue):
        def get_nowait(self):
            raise asyncio.QueueEmpty()

    q = _BadQueue(maxsize=1)
    q.put_nowait(b"old")
    StreamingServer._put_or_drop(q, b"new")
    loop.close()


def test_put_or_drop_second_put_failure() -> None:
    class _OneShotQueue:
        def __init__(self) -> None:
            self._full = True

        def put_nowait(self, item) -> None:
            if self._full:
                self._full = False
                raise asyncio.QueueFull()
            raise asyncio.QueueFull()

        def get_nowait(self):
            return b"old"

    StreamingServer._put_or_drop(_OneShotQueue(), b"new")


def test_safe_put_swallows_call_soon_threadsafe_errors() -> None:
    server = StreamingServer()
    loop, runner = _attach_loop(server)

    class _BrokenLoop:
        def call_soon_threadsafe(self, *_args, **_kwargs) -> None:
            raise RuntimeError("loop gone")

    server._loop = _BrokenLoop()
    server.push_telemetry({"kind": "gsi"})
    _stop_loop(loop, runner)


def test_start_in_thread_is_idempotent(monkeypatch) -> None:
    pytest.importorskip("uvicorn")

    class _FakeUvicornServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            while not self.should_exit:
                await asyncio.sleep(0.01)

    class _FakeConfig:
        def __init__(self, app, host, port, log_level, access_log):
            self.app = app
            self.host = host
            self.port = port

    monkeypatch.setattr("uvicorn.Config", _FakeConfig)
    monkeypatch.setattr("uvicorn.Server", _FakeUvicornServer)

    server = StreamingServer(host="127.0.0.1", port=18767)
    server.start_in_thread()
    thread1 = server._thread
    server.start_in_thread()
    assert server._thread is thread1
    server.stop(timeout=2.0)


def test_telemetry_websocket_disconnect_is_swallowed() -> None:
    from starlette.websockets import WebSocketDisconnect

    server = StreamingServer()
    endpoint = next(
        r.endpoint for r in server.app.routes if getattr(r, "path", None) == "/telemetry"
    )

    class _MockWebSocket:
        async def accept(self) -> None:
            return None

        async def send_text(self, _payload: str) -> None:
            raise WebSocketDisconnect()

    async def _run() -> None:
        task = asyncio.create_task(endpoint(_MockWebSocket()))
        while not server._telemetry_subscribers:
            await asyncio.sleep(0)
        queue = next(iter(server._telemetry_subscribers))
        await queue.put({"kind": "gsi", "mode": "Scan"})
        await task
        assert server.listener_counts()["telemetry"] == 0

    asyncio.run(_run())
