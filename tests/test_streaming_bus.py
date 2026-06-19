"""Tests for ``streaming.bus`` pub/sub."""

from __future__ import annotations

from streaming.bus import GLOBAL_BUS, StreamingBus


def test_subscribe_and_publish_delivers_payload() -> None:
    bus = StreamingBus()
    received: list[str] = []

    def handler(payload: str) -> None:
        received.append(payload)

    bus.subscribe("audio", handler)
    bus.publish("audio", "chunk-a")
    assert received == ["chunk-a"]


def test_unsubscribe_stops_delivery() -> None:
    bus = StreamingBus()
    received: list[int] = []

    def handler(payload: int) -> None:
        received.append(payload)

    bus.subscribe("telemetry", handler)
    bus.unsubscribe("telemetry", handler)
    bus.publish("telemetry", 42)
    assert received == []


def test_unsubscribe_unknown_topic_is_safe() -> None:
    bus = StreamingBus()
    bus.unsubscribe("missing", lambda x: None)


def test_publish_isolates_subscriber_exceptions() -> None:
    bus = StreamingBus()
    good: list[str] = []

    def bad(_payload: object) -> None:
        raise RuntimeError("boom")

    def good_handler(payload: str) -> None:
        good.append(payload)

    bus.subscribe("topic", bad)
    bus.subscribe("topic", good_handler)
    bus.publish("topic", "still-delivered")
    assert good == ["still-delivered"]


def test_clear_removes_all_subscribers() -> None:
    bus = StreamingBus()
    received: list[str] = []

    bus.subscribe("a", lambda p: received.append(p))
    bus.subscribe("b", lambda p: received.append(p))
    bus.clear()
    bus.publish("a", "x")
    bus.publish("b", "y")
    assert received == []


def test_topics_are_independent() -> None:
    bus = StreamingBus()
    audio: list[bytes] = []
    telemetry: list[dict] = []

    bus.subscribe("audio", audio.append)
    bus.subscribe("telemetry", telemetry.append)
    bus.publish("audio", b"\x00")
    bus.publish("telemetry", {"kind": "gsi"})
    assert audio == [b"\x00"]
    assert telemetry == [{"kind": "gsi"}]


def test_global_bus_is_shared_singleton() -> None:
    """GLOBAL_BUS is module-level; verify it behaves like a normal bus."""
    token = object()
    seen: list[object] = []

    def handler(payload: object) -> None:
        seen.append(payload)

    GLOBAL_BUS.subscribe("_test_global", handler)
    try:
        GLOBAL_BUS.publish("_test_global", token)
        assert seen == [token]
    finally:
        GLOBAL_BUS.unsubscribe("_test_global", handler)
