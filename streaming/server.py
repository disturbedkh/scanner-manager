"""FastAPI streaming server.

Endpoints:

- ``GET /audio``         - chunked audio stream (codec mime auto-set)
- ``GET /healthz``       - liveness probe
- ``GET /viewer``        - bundled HTML viewer (audio + telemetry)
- ``WS  /telemetry``     - JSON frames merged from GSI / GLG / FFT

The server runs in a background uvicorn ``Server`` started by
:meth:`StreamingServer.start_in_thread`, so the Qt event loop stays
responsive. :meth:`stop` blocks until uvicorn exits.

The audio source is an :class:`audio.encoder.AudioEncoder` instance
fed by :class:`audio.capture.AudioCapture`. The streaming dock owns
both pieces; this module is just the HTTP / websocket surface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Import FastAPI types at module scope so type annotations on the
# nested route handlers resolve correctly. Without this, FastAPI's
# get_type_hints() falls back to treating the WebSocket parameter as
# a query string field.
try:
    from fastapi import WebSocket as _WebSocket, WebSocketDisconnect as _WebSocketDisconnect
except ImportError:  # pragma: no cover
    _WebSocket = None  # type: ignore
    _WebSocketDisconnect = None  # type: ignore


_VIEWER_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Scanner Manager - Live</title>
<style>
    body { background: #1f1f1f; color: #ddd; font-family: sans-serif; padding: 20px; }
    h2 { margin-top: 0; }
    .panel { background: #2a2a2a; border: 1px solid #3a3a3a; padding: 16px;
             border-radius: 6px; margin-bottom: 16px; }
    .meter { background: #444; height: 14px; border-radius: 4px; overflow: hidden; }
    .meter > div { background: linear-gradient(90deg, #5cb85c, #f0ad4e, #d9534f);
                   height: 100%; width: 0%; transition: width 0.1s; }
    audio { width: 100%; }
    code { background: #111; padding: 2px 6px; border-radius: 3px; }
    table { width: 100%; border-collapse: collapse; }
    td { padding: 4px 6px; border-bottom: 1px solid #333; vertical-align: top; }
    td:first-child { color: #888; width: 30%; }
</style>
</head>
<body>
<h2>Scanner Manager — Live Listener</h2>

<div class="panel">
    <h3>Audio</h3>
    <audio id="player" controls autoplay>
        <source src="/audio" />
    </audio>
</div>

<div class="panel">
    <h3>Telemetry</h3>
    <table id="telemetry">
        <tr><td>Mode</td><td id="t-mode">—</td></tr>
        <tr><td>System</td><td id="t-system">—</td></tr>
        <tr><td>Department</td><td id="t-department">—</td></tr>
        <tr><td>Talkgroup</td><td id="t-tg">—</td></tr>
        <tr><td>Frequency</td><td id="t-freq">—</td></tr>
        <tr><td>Receiving</td><td id="t-rx">—</td></tr>
    </table>
    <div class="meter" style="margin-top: 12px;">
        <div id="t-signal"></div>
    </div>
    <p>RSSI: <code id="t-rssi">—</code></p>
</div>

<div class="panel">
    <h3>Recent calls</h3>
    <ul id="calls" style="list-style:none; padding:0; margin:0;"></ul>
</div>

<script>
const $ = id => document.getElementById(id);
const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
const ws = new WebSocket(proto + location.host + '/telemetry');
ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.kind === 'gsi') {
        $('t-mode').textContent = msg.mode || '—';
        $('t-system').textContent = msg.system_name || '—';
        $('t-department').textContent = msg.department_name || '—';
        $('t-tg').textContent = msg.tg_name || '—';
        $('t-freq').textContent = msg.frequency_hz
            ? (msg.frequency_hz / 1e6).toFixed(5) + ' MHz' : '—';
        $('t-rx').textContent = msg.is_receiving ? 'YES' : 'no';
        $('t-rssi').textContent = (msg.rssi_dbm == null) ? '—' : msg.rssi_dbm + ' dBm';
        const pct = msg.signal_pct == null ? 0 : msg.signal_pct;
        $('t-signal').style.width = Math.max(0, Math.min(100, pct)) + '%';
    } else if (msg.kind === 'glg' && msg.is_receiving) {
        const li = document.createElement('li');
        const ts = new Date().toLocaleTimeString();
        li.textContent = ts + '  |  ' + (msg.name1 || '') + ' > ' + (msg.name2 || '') + ' > ' + (msg.name3 || '');
        const ul = $('calls');
        ul.insertBefore(li, ul.firstChild);
        while (ul.childElementCount > 50) ul.removeChild(ul.lastChild);
    }
};
ws.onclose = () => setTimeout(() => location.reload(), 2000);
</script>
</body>
</html>
"""


class StreamingServer:
    """FastAPI app + uvicorn launcher + audio/telemetry pub-sub."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._encoder = None  # set via set_encoder()
        self._audio_subscribers: Set[Any] = set()
        self._telemetry_subscribers: Set[Any] = set()
        self._lock = threading.Lock()
        self._uvicorn_server = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # FastAPI app
    # ------------------------------------------------------------------

    def _build_app(self):
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, StreamingResponse
        # Use the module-level WebSocket aliases so FastAPI's annotation
        # resolver finds them when validating the route handler.
        WebSocket = _WebSocket
        WebSocketDisconnect = _WebSocketDisconnect

        app = FastAPI(title="Scanner Manager", version="1.0")

        @app.get("/healthz")
        async def healthz() -> Dict[str, Any]:
            return {"ok": True, "audio_listeners": len(self._audio_subscribers),
                    "telemetry_listeners": len(self._telemetry_subscribers)}

        @app.get("/viewer", response_class=HTMLResponse)
        async def viewer() -> str:
            return _VIEWER_HTML

        @app.get("/")
        async def index() -> Dict[str, Any]:
            return {
                "name": "Scanner Manager streaming server",
                "endpoints": {
                    "audio": "/audio",
                    "telemetry": "/telemetry (websocket)",
                    "viewer": "/viewer",
                    "health": "/healthz",
                },
            }

        @app.get("/audio")
        async def audio():
            queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=64)
            with self._lock:
                self._audio_subscribers.add(queue)
            mime = "audio/wav"
            if self._encoder is not None:
                mime = self._encoder.mime_type

            async def gen():
                try:
                    # If we're not yet capturing, the queue stays empty
                    # until the dock starts. Send a "starting" delay
                    # so curl/ffplay can't time out instantly.
                    while True:
                        chunk = await queue.get()
                        if chunk is None:
                            break
                        yield chunk
                finally:
                    with self._lock:
                        self._audio_subscribers.discard(queue)

            return StreamingResponse(gen(), media_type=mime)

        @app.websocket("/telemetry")
        async def telemetry(websocket: _WebSocket) -> None:
            await websocket.accept()
            queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=200)
            with self._lock:
                self._telemetry_subscribers.add(queue)
            try:
                while True:
                    msg = await queue.get()
                    if msg is None:
                        break
                    await websocket.send_text(json.dumps(msg, default=str))
            except _WebSocketDisconnect:
                pass
            finally:
                with self._lock:
                    self._telemetry_subscribers.discard(queue)
        return app

    # ------------------------------------------------------------------
    # Public API used by the streaming dock
    # ------------------------------------------------------------------

    @property
    def app(self):
        return self._app

    def set_encoder(self, encoder) -> None:
        """Hand the server the encoder so its mime type is correct."""
        self._encoder = encoder

    def push_audio_chunk(self, data: bytes) -> None:
        """Forward an encoded audio chunk to every active listener."""
        if not data:
            return
        if self._loop is None:
            return
        with self._lock:
            queues = list(self._audio_subscribers)
        for q in queues:
            self._safe_put(q, data)

    def push_telemetry(self, payload: Dict[str, Any]) -> None:
        """Forward a JSON-serializable dict to every websocket listener."""
        if self._loop is None:
            return
        with self._lock:
            queues = list(self._telemetry_subscribers)
        for q in queues:
            self._safe_put(q, payload)

    def _safe_put(self, queue, item) -> None:
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._put_or_drop, queue, item)
        except Exception:
            pass

    @staticmethod
    def _put_or_drop(queue, item) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Drop oldest, push newest (so listeners always see the
            # freshest telemetry / audio).
            try:
                queue.get_nowait()
            except Exception:
                return
            try:
                queue.put_nowait(item)
            except Exception:
                return

    def listener_counts(self) -> Dict[str, int]:
        return {
            "audio": len(self._audio_subscribers),
            "telemetry": len(self._telemetry_subscribers),
        }

    # ------------------------------------------------------------------
    # Uvicorn lifecycle
    # ------------------------------------------------------------------

    def start_in_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError("uvicorn not installed") from exc

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(server.serve())
            finally:
                self._loop = None

        self._thread = threading.Thread(target=runner, name="streaming-server", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        server = self._uvicorn_server
        if server is None:
            return
        server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._uvicorn_server = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
