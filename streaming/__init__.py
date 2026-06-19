"""Streaming subsystem.

Modules:

- :mod:`streaming.server` - FastAPI app exposing ``/audio.<ext>``,
  ``/telemetry`` (websocket), ``/viewer`` (HTML).
- :mod:`streaming.broadcastify` - Broadcastify push (Icecast2 source
  client targeting the published feed mount).
- :mod:`streaming.icecast` - generic Icecast2 source client for
  self-hosted relays.
- :mod:`streaming.bus` - typed pub/sub between the live-mode driver
  layer, the audio capture, and the server's listener loops.
"""

from __future__ import annotations

__all__ = ["server", "broadcastify", "icecast", "bus"]
