"""
Thread-safe event bus for GUI <-> worker communication.
Workers publish events from background threads; the main thread polls and dispatches.
"""

import queue
import threading
from typing import Any, Callable, Dict, List


class EventBus:
    """Simple publish/subscribe event bus backed by a thread-safe queue."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._sub_lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to an event type. Callback runs on the main thread."""
        with self._sub_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        """Remove a subscription."""
        with self._sub_lock:
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    cb for cb in self._subscribers[event_type] if cb is not callback
                ]

    def publish(self, event_type: str, data: Any = None):
        """Publish an event (safe to call from any thread)."""
        self._queue.put((event_type, data))

    def poll(self):
        """Process all pending events. Call from the main thread only."""
        processed = 0
        while processed < 50:  # Cap per poll to avoid UI freezing
            try:
                event_type, data = self._queue.get_nowait()
            except queue.Empty:
                break
            # Snapshot subscriber list under lock
            with self._sub_lock:
                callbacks = list(self._subscribers.get(event_type, []))
            for callback in callbacks:
                try:
                    callback(data)
                except Exception:
                    pass  # Don't let one bad handler block others
            processed += 1
