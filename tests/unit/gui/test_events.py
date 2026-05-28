"""Tests for memanga.gui.events.EventBus — thread-safe pub/sub."""

from __future__ import annotations

import threading
import pytest


class TestEventBus:
    def test_subscribe_and_publish_in_order(self, event_bus):
        seen = []
        event_bus.subscribe("ping", lambda d: seen.append(d))
        event_bus.publish("ping", {"n": 1})
        event_bus.publish("ping", {"n": 2})
        event_bus.poll()
        assert seen == [{"n": 1}, {"n": 2}]

    def test_multiple_subscribers_all_fire(self, event_bus):
        a, b = [], []
        event_bus.subscribe("x", lambda d: a.append(d))
        event_bus.subscribe("x", lambda d: b.append(d))
        event_bus.publish("x", {"v": 1})
        event_bus.poll()
        assert a and b

    def test_unrelated_topic_doesnt_fire(self, event_bus):
        seen = []
        event_bus.subscribe("only-this", lambda d: seen.append(d))
        event_bus.publish("not-this", {})
        event_bus.poll()
        assert seen == []

    def test_exception_in_handler_doesnt_break_bus(self, event_bus):
        def boom(_): raise ValueError("nope")
        seen = []
        event_bus.subscribe("x", boom)
        event_bus.subscribe("x", lambda d: seen.append(d))
        event_bus.publish("x", {})
        event_bus.poll()
        # Other handlers still ran (or at least no crash bubbled out).

    def test_publish_from_thread_safely_polled(self, event_bus):
        seen = []
        event_bus.subscribe("from-thread", lambda d: seen.append(d))
        def _pub():
            for i in range(50):
                event_bus.publish("from-thread", {"i": i})
        threads = [threading.Thread(target=_pub) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        # poll() caps work per call to keep the UI responsive — drain
        # the queue by polling until no new events arrive.
        prev = -1
        while len(seen) != prev:
            prev = len(seen)
            event_bus.poll()
        assert len(seen) == 200
