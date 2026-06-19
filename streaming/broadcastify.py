"""Broadcastify push helper.

Broadcastify accepts source-client pushes via Icecast2's HTTP-source
protocol on their dedicated streaming hosts. The user provides:

- mount (e.g. ``/12345``)
- password (per-feed, set in the Broadcastify dashboard)
- optional host override (defaults to the published Broadcastify mount)

This module is a thin :class:`~streaming.icecast.IcecastPusher`
wrapper that pre-fills the host + content type appropriately for
Broadcastify's published config.

Note: shipping the wiring is **not** the same as shipping
credentials. The user pastes their own per-feed password into the
streaming dock; we never ship one.
"""

from __future__ import annotations

import logging

from .icecast import IcecastPusher

logger = logging.getLogger(__name__)

# Default ingest host published in Broadcastify's source-client
# instructions (https://www.broadcastify.com/calls/feeds/help/source/).
# Subject to change; users with a different ingest host can override
# via the streaming dock's "Advanced" section.
DEFAULT_BROADCASTIFY_HOST = "audio1.broadcastify.com"
DEFAULT_BROADCASTIFY_PORT = 80


class BroadcastifyPusher(IcecastPusher):
    """Convenience subclass with Broadcastify defaults."""

    def __init__(
        self,
        mount: str,
        password: str,
        username: str = "source",
        host: str = DEFAULT_BROADCASTIFY_HOST,
        port: int = DEFAULT_BROADCASTIFY_PORT,
        bitrate_kbps: int = 16,
        content_type: str = "audio/mpeg",
        use_tls: bool = False,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            mount=mount,
            password=password,
            username=username,
            content_type=content_type,
            bitrate_kbps=bitrate_kbps,
            use_tls=use_tls,
        )
