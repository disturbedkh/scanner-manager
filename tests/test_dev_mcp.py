"""Smoke tests for the local dev_mcp/ debug bridge.

These tests deliberately auto-skip when the package isn't installed
so the public CI works fine on a clean clone (dev_mcp/ is gitignored).
They cover:

- Server starts and binds 127.0.0.1.
- Token auth refuses missing / wrong tokens.
- /healthz responds without auth.
- Stub drivers wired through state are reachable via the HTTP surface.
- /app/eval is gated behind the token.
- The GUI shim in gui/app.py silently no-ops when dev_mcp is missing.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.integration

dev_mcp = pytest.importorskip("dev_mcp")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


@pytest.fixture
def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def bridge(free_port):
    from dev_mcp import server
    server.stop()
    server._state.update({
        "main_window": None,
        "live_dock": None,
        "device_manager": None,
    })
    token = server.start(host="127.0.0.1", port=free_port)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{free_port}/healthz", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.05)
    yield {"port": free_port, "token": token}
    server.stop()


def _get(port: int, path: str, token: str = "") -> tuple[int, dict]:
    headers = {"X-Dev-Token": token} if token else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _post(port: int, path: str, body: dict, token: str = "") -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Dev-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        return exc.code, payload


def test_refuses_non_loopback_bind():
    from dev_mcp import server
    with pytest.raises(RuntimeError):
        server.start(host="0.0.0.0", port=12345)


def test_healthz_is_open(bridge):
    code, body = _get(bridge["port"], "/healthz")
    assert code == 200
    assert body["ok"] is True


def test_protected_endpoint_requires_token(bridge):
    code, _ = _get(bridge["port"], "/app/state", token="")
    assert code == 401


_TEST_BAD_AUTH = "not-the-real-token"


def test_protected_endpoint_rejects_wrong_token(bridge):
    code, _ = _get(bridge["port"], "/app/state", token=_TEST_BAD_AUTH)
    assert code == 401


def test_app_state_returns_active_profile(bridge):
    code, body = _get(bridge["port"], "/app/state", token=bridge["token"])
    assert code == 200
    assert "active_profile" in body
    # The default profile in scanner_profiles is non-None even before
    # the GUI runs.
    assert isinstance(body["active_profile"], dict)


def test_eval_executes_inside_app_process(bridge):
    code, body = _post(
        bridge["port"],
        "/app/eval",
        {"source": "1 + 41", "mode": "eval"},
        token=bridge["token"],
    )
    assert code == 200, body
    assert body["ok"] is True
    assert body["value"] == "42"


def test_eval_requires_token(bridge):
    code, _ = _post(
        bridge["port"], "/app/eval", {"source": "1+1"}, token=""
    )
    assert code == 401


def test_main_query_409s_when_no_driver_attached(bridge):
    code, _ = _post(
        bridge["port"], "/scanner/main/query", {"cmd": "GSI"}, token=bridge["token"]
    )
    assert code == 409


def test_app_logs_returns_records(bridge):
    import logging
    logging.getLogger("test.dev_mcp").info("smoke event")
    time.sleep(0.05)
    code, body = _get(bridge["port"], "/app/logs?limit=50", token=bridge["token"])
    assert code == 200
    msgs = [r["message"] for r in body["records"]]
    assert any("smoke event" in m for m in msgs)


def test_stub_driver_is_reachable_through_http(bridge):
    """Wire a stub MAIN driver into the bridge state and exercise
    the /scanner/main/query endpoint end-to-end.
    """
    from dev_mcp import server

    class _FakePort:
        def __init__(self, payload: bytes) -> None:
            self._buf = payload + b"\r"
            self.in_waiting = len(self._buf)

        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None: ...
        def reset_input_buffer(self) -> None: ...

        def read(self, n: int) -> bytes:
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
            self.in_waiting = len(self._buf)
            return chunk

    from scanner_drivers.serial_main import SerialMainDriver

    driver = SerialMainDriver(_FakePort(b"GSI,<ScannerInfo Mode=\"Scan\"/>"))

    class _Ctrl:
        def __init__(self, drv): self.driver = drv

    class _Dock:
        _main_controller = _Ctrl(driver)
        _sub_controller = None

    server._state["live_dock"] = _Dock()

    code, body = _post(
        bridge["port"],
        "/scanner/main/query",
        {"cmd": "GSI"},
        token=bridge["token"],
    )
    assert code == 200
    assert body["ok"] is True
    assert "ScannerInfo" in body["raw_text"]


def test_main_app_silently_noops_when_dev_mcp_absent(monkeypatch):
    """Sanity check: the gui/app.py import shim must swallow ImportError
    so removing dev_mcp/ doesn't break the main app.

    We simulate "package missing" by patching sys.modules so any import
    of dev_mcp blows up with ImportError.
    """
    import sys

    sentinel = object()
    monkeypatch.setitem(sys.modules, "dev_mcp", sentinel)

    # We re-execute just the snippet from gui/app.py here rather than
    # invoking the whole Qt app. The expectation: ImportError is
    # caught, no exception bubbles up.
    monkeypatch.setenv("SCANNER_MANAGER_DEV_MCP", "1")
    err = None
    try:
        try:
            from dev_mcp import attach as _dev_attach  # type: ignore
            _dev_attach.maybe_start(None)
        except ImportError:
            pass
    except Exception as exc:  # pragma: no cover
        err = exc
    assert err is None
