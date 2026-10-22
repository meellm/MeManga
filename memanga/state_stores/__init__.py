"""Focused domain stores over the single ``state.json`` (issue #225).

``State`` (memanga/state.py) owns persistence and locking and exposes one
store per domain::

    state.library        LibraryStore        downloaded chapters, entries
    state.catalogue      CatalogueStore      available chapters, badges
    state.backups        BackupStore         pending backups, suspicious batches
    state.failures       FailureStore        failed, partial, undelivered
    state.reading        ReadingStore        progress, positions, read set
    state.notifications  NotificationStore   notification log
    state.searches       SearchHistoryStore  recent searches
    state.activity       ActivityStore       check/download history, stats
    state.source_health  SourceHealthStore   source probe results

New code should call the stores; the flat ``State`` methods remain as
compatibility wrappers for existing callers.
"""

from ._base import StateBackend, StateDomain
from .activity import ActivityStore
from .backups import BackupStore
from .catalogue import CatalogueStore
from .failures import FailureStore
from .library import LibraryStore
from .notifications import NotificationStore
from .reading import ReadingStore
from .searches import SearchHistoryStore
from .source_health import SourceHealthStore

__all__ = [
    "ActivityStore",
    "BackupStore",
    "CatalogueStore",
    "FailureStore",
    "LibraryStore",
    "NotificationStore",
    "ReadingStore",
    "SearchHistoryStore",
    "SourceHealthStore",
    "StateBackend",
    "StateDomain",
]
