"""Tests for ``streaming.server`` using FastAPI's TestClient."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from scanner_drivers.serial_main import GsiSnapshot  # noqa: E402
from streaming.server import StreamingServer  # noqa: E402


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
    # No assertion needed - test passes if no exception
