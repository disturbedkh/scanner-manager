"""Lightweight pub/sub bus for streaming feeds.

The streaming dock collects events from three sources:

- audio :class:`~audio.capture.AudioCapture` (encoded byte chunks)
- live-dock GSI / GLG / waterfall payloads
- streaming-server lifecycle events (listener joined/left)

Each subscriber registers a callback; the bus calls every callback
synchronously when :meth:`publish` is called. Failures in one
subscriber don't break the others. The implementation is GIL-bound
+ thread-safe (one lock around the subscriber set).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, Set

logger = logging.getLogger(__name__)


class StreamingBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[Callable[[Any], None]]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        with self._lock:
            self._subscribers[topic].add(callback)

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        with self._lock:
            self._subscribers.get(topic, set()).discard(callback)

    def publish(self, topic: str, payload: Any) -> None:
        with self._lock:
            subs = list(self._subscribers.get(topic, ()))
        for cb in subs:
            try:
                cb(payload)
            except Exception:
                logger.exception("subscriber raised on topic %r", topic)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


GLOBAL_BUS = StreamingBus()
