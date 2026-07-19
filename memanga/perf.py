"""
Lightweight opt-in timing instrumentation shared by the GUI and CLI.

Disabled by default so production runs stay quiet. Enable with the
``MEMANGA_PERF`` environment variable (``1``/``true``/``yes``/``on``)
or programmatically via :func:`set_enabled` (used by tests).

When enabled, each timed block logs its duration at DEBUG level on the
``memanga.perf`` logger and appends a ``(name, duration_ms)`` sample to
a bounded in-memory buffer readable via :func:`recent_samples`. When
disabled, :func:`timed` costs a single boolean check per call.

Usage::

    from .perf import timed

    @timed("state.save")          # as a decorator
    def save(self): ...

    with timed("gui.library.refresh"):   # or as a context manager
        rebuild()
"""

import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Deque, List, Optional, Tuple

logger = logging.getLogger("memanga.perf")

# Bounded so a long session can't grow memory. Samples arrive from worker
# threads, so append/clear/snapshot share a lock: iterating a deque while
# another thread appends raises "deque mutated during iteration".
_MAX_SAMPLES = 200
_samples: Deque[Tuple[str, float]] = deque(maxlen=_MAX_SAMPLES)
_samples_lock = threading.Lock()

_TRUTHY = {"1", "true", "yes", "on"}

# None means "not resolved yet - read the environment on first use".
_enabled: Optional[bool] = None


def is_enabled() -> bool:
    """Whether timing collection is active."""
    global _enabled
    if _enabled is None:
        _enabled = os.environ.get("MEMANGA_PERF", "").strip().lower() in _TRUTHY
    return _enabled


def set_enabled(value: Optional[bool]):
    """Force collection on/off; ``None`` re-reads the environment."""
    global _enabled
    _enabled = value


def clear_samples():
    with _samples_lock:
        _samples.clear()


def recent_samples() -> List[Tuple[str, float]]:
    """Snapshot of the most recent ``(name, duration_ms)`` samples."""
    with _samples_lock:
        return list(_samples)


@contextmanager
def timed(name: str):
    """Time a block (or, used as a decorator, a call) under ``name``."""
    if not is_enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        with _samples_lock:
            _samples.append((name, duration_ms))
        logger.debug("%s took %.1f ms", name, duration_ms)
