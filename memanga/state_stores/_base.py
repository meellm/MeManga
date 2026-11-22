"""Shared pieces of the state domain stores (issue #225).

``State`` (memanga/state.py) owns the single ``state.json`` file, its
recovery, the reentrant lock and the dirty flag. Each domain store holds a
reference to that ``State`` and reaches the data only through the small
backend contract below, so every store shares one file, one lock and one
dirty flag. Stores never keep a reference to ``_data`` itself:
``State.clear_all()`` rebinds it.
"""

from __future__ import annotations

import copy
from contextlib import AbstractContextManager
from typing import Any, Dict, Protocol


class StateBackend(Protocol):
    """Persistence and locking contract the domain stores rely on.

    Implemented by ``State``. Members are looked up on the instance at
    call time, so a replaced lock or dirty hook on a ``State`` instance
    applies to every store.
    """

    def _locked(self) -> AbstractContextManager[Dict[str, Any]]:
        """Hold the shared lock and yield the live state data."""

    def _mark_dirty(self) -> None:
        """Mark the state as modified; the next flush writes it."""

    def save(self) -> None:
        """Write the state file now."""

    def _ensure_manga_entry(self, manga_title: str) -> None:
        """Create the manga entry if missing. Caller holds the lock."""

    def _entry_value(self, manga_title: str, key: str, default: Any = None) -> Any:
        """Snapshot of one field of a manga entry, read under the lock."""


class StateDomain:
    """Base class for a focused view onto one domain of the state file."""

    __slots__ = ("_backend",)

    def __init__(self, backend: StateBackend) -> None:
        self._backend = backend


def snapshot(value: Any) -> Any:
    """Deep-copy container values so nothing a caller receives (or
    passes in) aliases the stored data — shallow copies still leaked the
    dicts nested inside returned lists, e.g. editing a row from
    get_available_chapters() changed stored state. Everything in the state
    is plain JSON types, so deepcopy stays cheap relative to the GUI work
    that consumes these snapshots.
    """
    return copy.deepcopy(value) if isinstance(value, (dict, list)) else value
