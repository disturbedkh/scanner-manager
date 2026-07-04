"""Tests for ``streaming.broadcastify``.

Broadcastify pushing is a thin :class:`~streaming.icecast.IcecastPusher`
subclass that pre-fills the published ingest host + content type. These
tests pin the Broadcastify-specific defaults and the override path so the
subclass can't silently drift from the parent contract.
"""

from __future__ import annotations

from streaming.broadcastify import (
    DEFAULT_BROADCASTIFY_HOST,
    DEFAULT_BROADCASTIFY_PORT,
    BroadcastifyPusher,
)
from streaming.icecast import IcecastPusher

# Per-feed password the user would paste into the dock; never a real secret.
TEST_FEED_PASSWORD = "feed-stub-pw"


def test_broadcastify_is_icecast_subclass() -> None:
    assert issubclass(BroadcastifyPusher, IcecastPusher)


def test_broadcastify_defaults() -> None:
    pusher = BroadcastifyPusher(mount="/12345", password=TEST_FEED_PASSWORD)
    assert pusher.host == DEFAULT_BROADCASTIFY_HOST
    assert pusher.port == DEFAULT_BROADCASTIFY_PORT
    assert pusher.mount == "/12345"
    assert pusher.username == "source"
    assert pusher.content_type == "audio/mpeg"
    assert pusher.use_tls is False
    assert pusher.bitrate_kbps == 16
    assert pusher.password == TEST_FEED_PASSWORD


def test_broadcastify_mount_is_normalized() -> None:
    # The parent prepends a leading slash when the mount lacks one.
    pusher = BroadcastifyPusher(mount="98765", password=TEST_FEED_PASSWORD)
    assert pusher.mount == "/98765"


def test_broadcastify_overrides_passthrough() -> None:
    pusher = BroadcastifyPusher(
        mount="/7",
        password=TEST_FEED_PASSWORD,
        host="audio2.broadcastify.com",
        port=8000,
        bitrate_kbps=32,
        use_tls=True,
    )
    assert pusher.host == "audio2.broadcastify.com"
    assert pusher.port == 8000
    assert pusher.bitrate_kbps == 32
    assert pusher.use_tls is True
