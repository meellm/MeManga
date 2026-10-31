"""
State management for MeManga - tracks downloaded chapters and check history

``State`` owns the single ``state.json`` file: loading and recovery,
atomic saves with a ``.bak`` copy, the dirty flag and the shared lock.
The rules of each domain live in focused stores (``memanga.state_stores``)
reachable as attributes, e.g. ``state.reading`` or ``state.failures``.
"""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Mapping

from .config import default_config_dir
from .perf import timed
from .persist import atomic_write_text, preserve_corrupt
from .schema import (SCHEMA_VERSION_KEY, SchemaVersionError, add_schema_version,
                     migrate as migrate_schema)
from .state_stores import (ActivityStore, BackupStore, CatalogueStore,
                           FailureStore, LibraryStore, NotificationStore,
                           ReadingStore, SearchHistoryStore,
                           SourceHealthStore)
from .state_stores._base import snapshot as _snapshot_value
# Re-exported: existing callers import the chapter helpers from here.
from .chapters import (  # noqa: F401
    CHAPTER_NUMBER_RE as _CHAPTER_NUMBER_RE,
    chapter_number as _chapter_number,
    chapter_sort_key as _chapter_sort_key,
)


# Issue #409: layout version of state.json (see memanga.schema). When
# it is bumped, register ``old_version: migrate_fn`` below.
STATE_SCHEMA_VERSION = 1
_STATE_MIGRATIONS = {
    0: add_schema_version,
}


class StateError(Exception):
    """The state file exists but could not be loaded or kept safe."""


class State:
    """Manages state file (tracking what's been downloaded).

    Uses a dirty flag and thread lock to batch saves and prevent corruption.
    Call flush() explicitly when you need the file written immediately.

    Issue #110: the GUI mutates state from background workers (checks,
    downloads, source-health probes) while the main thread flushes it
    periodically and on close. Every public method therefore takes the
    same reentrant lock via ``_locked()``. Getters return deep snapshots
    (nested containers included) and container-accepting setters store
    snapshots, so no caller ever holds a live alias into ``_data``.

    Issue #225: domain rules live in focused stores that share this
    object's file, lock and dirty flag (see ``memanga.state_stores``):
    ``library``, ``catalogue``, ``backups``, ``failures``, ``reading``,
    ``notifications``, ``searches``, ``activity`` and ``source_health``.
    The flat methods below the persistence layer are compatibility
    wrappers that delegate to those stores.
    """

    # Kept here for existing callers; owned by SourceHealthStore.
    SLOW_LATENCY_MS = SourceHealthStore.SLOW_LATENCY_MS

    def __init__(self, config_dir: Optional[Path] = None, recover: bool = True):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = default_config_dir()

        self.state_path = self.config_dir / "state.json"
        self.backup_path = self.config_dir / "state.json.bak"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Reentrant so mutators that persist immediately can call save()
        # (and nested public getters) while already holding the lock.
        self._lock = threading.RLock()
        self._dirty = False
        # Issue #243: set when state.json exists but cannot be loaded and
        # could not be copied aside or restored; save() then refuses to write so the
        # only copy is never replaced.
        self.load_error: Optional[str] = None
        # Set when a damaged state.json was copied aside on load; tells the
        # user where it went and what was loaded instead.
        self.recovery_notice: Optional[str] = None
        self.preserved_path: Optional[Path] = None
        # Issue #244: with ``recover=False`` (a read-only command that does
        # not hold the config directory lock) a damaged state.json is not
        # copied aside, removed or restored; ``needs_recovery`` is set and
        # loading fails instead, so nothing in the directory is changed.
        self._recover = recover
        self.needs_recovery = False
        # Issue #225: one store per domain, all backed by this object.
        self.library = LibraryStore(self)
        self.catalogue = CatalogueStore(self)
        self.backups = BackupStore(self)
        self.failures = FailureStore(self)
        self.reading = ReadingStore(self)
        self.notifications = NotificationStore(self)
        self.searches = SearchHistoryStore(self)
        self.activity = ActivityStore(self)
        self.source_health = SourceHealthStore(self)
        self._data, restored = self._load()
        if restored:
            self._write_back_restored()
        self._migrate_schema()

    def _migrate_schema(self):
        """Bring the loaded state up to STATE_SCHEMA_VERSION (issue #409).

        Only ``_data`` changes: the next save writes the upgraded layout
        and keeps the file it replaces as state.json.bak, and a read-only
        command never writes it. Runs after _write_back_restored so a
        restored backup is written back as it was. A state file from a
        newer MeManga (or with an invalid version) sets ``load_error`` so
        it is never overwritten.
        """
        try:
            self._data = migrate_schema(self._data, STATE_SCHEMA_VERSION,
                                        _STATE_MIGRATIONS, "state")
        except SchemaVersionError as e:
            self.recovery_notice = None
            self.load_error = f"{self.state_path}: {e}"
            self._data = self._default_state()

    def _write_back_restored(self):
        """Replace the damaged state.json with the copy restored from
        state.json.bak.

        The damaged file stays in place until this write succeeds, so a
        start never finds state.json missing after a failed recovery (a
        missing file is a fresh start). No backup rotation here: that
        would turn the damaged file into the backup. If the write fails,
        refuse to run on this state: load_error is set, saves are refused,
        state.json stays damaged (the next start retries the restore) and
        state.json.bak is left as it is.
        """
        payload = json.dumps(self._data, indent=None, default=str)
        try:
            atomic_write_text(self.state_path, payload)
            return
        except OSError as e:
            error = e
        self.recovery_notice = None
        self.load_error = (
            f"{self.state_path} is damaged and the previous copy in "
            f"{self.backup_path} could not be written back: {error}. "
            f"{self.state_path} was left as it is (a copy is kept as "
            f"{self.preserved_path}), and {self.backup_path} is unchanged."
        )

    def _read_state_file(self, path: Path) -> Dict[str, Any]:
        """Parse a state file. Raises OSError if it cannot be read and
        ValueError if its content is not a JSON object."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("does not contain a JSON object")
        return data

    def _load(self):
        """Load state from file. Returns ``(data, restored_from_backup)``.

        Issue #243: a damaged state.json used to be replaced by empty
        state on the next save, losing download history, read progress
        and source health. It is now copied aside (the copy is never
        overwritten) and the last good copy from state.json.bak is loaded
        when there is one; see _write_back_restored.
        """
        path = self.state_path
        if not path.exists():
            return self._default_state(), False
        try:
            return self._read_state_file(path), False
        except OSError as e:
            # Possibly temporary (permissions, I/O): keep the file in place.
            self.load_error = f"cannot read {path}: {e}"
            return self._default_state(), False
        except ValueError as e:
            problem = f"{path} is damaged ({e})"
        if not self._recover:
            self.needs_recovery = True
            self.load_error = (
                f"{problem}. It is only repaired while no other MeManga "
                f"process is using {self.config_dir}; nothing was changed. "
                "Retry when that process has finished."
            )
            return self._default_state(), False
        try:
            self.preserved_path = preserve_corrupt(path)
        except OSError as e:
            self.load_error = f"{problem}, and it could not be copied for recovery: {e}"
            return self._default_state(), False

        kept = f"{problem}. The damaged file was kept as {self.preserved_path}."
        try:
            data = self._read_state_file(self.backup_path)
        except (FileNotFoundError, ValueError):
            # Nothing to restore: drop the damaged original now that it is
            # copied. If that fails, the next save replaces it.
            try:
                os.unlink(path)
            except OSError:
                pass
            self.recovery_notice = (
                f"{kept} No usable backup was found, so MeManga started "
                "with empty state (download history, read progress and "
                "source health)."
            )
            return self._default_state(), False
        except OSError as e:
            # The backup exists but cannot be read now (permissions, I/O).
            # It may be the only good copy: refuse rather than start
            # empty, and leave both files where they are.
            self.load_error = (
                f"{kept} The backup {self.backup_path} could not be read: "
                f"{e}. {path} and the backup were left as they are."
            )
            return self._default_state(), False
        self.recovery_notice = (
            f"{kept} Restored the previous copy from {self.backup_path}; "
            "changes made after that save may be missing."
        )
        return data, True

    def _default_state(self) -> Dict[str, Any]:
        """Return default state structure."""
        return {
            SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION,
            "manga": {},
            "last_check": None,
            "check_history": [],
            "notifications": [],
            "download_history": [],
            "source_health": {},
        }

    @contextmanager
    def _locked(self):
        """Hold the state lock around a read or nested update of ``_data``.

        Issue #110: every public method accesses ``_data`` through this so
        background workers can't interleave with the main thread's periodic
        flush/save. Yields ``_data`` so method bodies stay readable.
        """
        with self._lock:
            yield self._data

    @staticmethod
    def _snapshot(value):
        """Deep-copy container values so nothing a caller receives (or
        passes in) aliases ``_data``; see ``state_stores._base.snapshot``.
        """
        return _snapshot_value(value)

    def _entry_value(self, manga_title: str, key: str, default=None):
        """Read one field of a manga entry under the lock.

        Containers come back as deep snapshots (see _snapshot). Cheaper
        than get_manga_state() for the per-chapter getters the GUI calls
        in row-rendering loops, since it doesn't snapshot the whole entry
        (notably the available_chapters cache).
        """
        with self._locked() as data:
            value = data.get("manga", {}).get(manga_title, {}).get(key, default)
            return self._snapshot(value)

    @timed("state.save")
    def save(self):
        """Save state to file atomically. Thread-safe.

        The previous file is kept as state.json.bak (issue #243). Raises
        StateError while ``load_error`` is set, so a state file that could
        not be loaded is never overwritten.
        """
        if self.load_error:
            raise StateError(
                f"Refusing to overwrite {self.state_path}: {self.load_error}"
            )
        with self._lock:
            data_snapshot = json.dumps(self._data, indent=None, default=str)
            atomic_write_text(self.state_path, data_snapshot,
                              backup_path=self.backup_path)
            self._dirty = False

    def _mark_dirty(self):
        """Mark state as modified. Use flush() to write to disk."""
        self._dirty = True

    def flush(self):
        """Write to disk only if state has been modified."""
        with self._lock:
            if self._dirty:
                self.save()

    def get(self, key: str, default=None):
        """Get a state value. Containers come back as deep copies so the
        caller can't race concurrent mutators; write changes back with
        set()."""
        with self._locked() as data:
            return self._snapshot(data.get(key, default))

    def set(self, key: str, value):
        """Set a state value and save immediately. Containers are stored
        as snapshots so later mutation by the caller can't reach ``_data``."""
        with self._locked() as data:
            data[key] = self._snapshot(value)
            self.save()


    def _ensure_manga_entry(self, manga_title: str):
        """Ensure manga entry exists in state. Caller must hold ``_lock``."""
        if "manga" not in self._data:
            self._data["manga"] = {}
        if manga_title not in self._data["manga"]:
            self._data["manga"][manga_title] = {
                "downloaded": [],
                "last_chapter": None,
                "last_updated": None,
                "created": datetime.now().isoformat(),
                "reading_progress": {"last_chapter": None, "last_read": None},
                "new_chapters_available": 0,
                "available_chapters": [],
                "external_chapters": [],
                "partial_chapters": {},
            }

    def clear_all(self):
        """Clear all state (fresh start)."""
        with self._lock:
            self._data = self._default_state()
            self.save()

    # ========================================================================
    # Compatibility wrappers (issue #225)
    #
    # Each method below keeps an existing ``State`` call working by
    # delegating to the store that owns the rule. New code should call the
    # store directly, e.g. ``state.reading.set_position(...)``.
    # ========================================================================

    # ── Library / downloads: state.library ─────────────────────────────

    def merge_missing_manga_state(
        self,
        imported_state: Dict[str, Any],
        *,
        merge_existing_downloaded: bool = False,
        title_aliases: Optional[Mapping[str, str]] = None,
    ) -> None:
        """See :meth:`LibraryStore.merge_missing`."""
        self.library.merge_missing(
            imported_state,
            merge_existing_downloaded=merge_existing_downloaded,
            title_aliases=title_aliases,
        )

    def get_manga_state(self, manga_title: str) -> Dict[str, Any]:
        """See :meth:`LibraryStore.get_entry`."""
        return self.library.get_entry(manga_title)

    def get_last_chapter(self, manga_title: str) -> Optional[str]:
        """See :meth:`LibraryStore.get_last_chapter`."""
        return self.library.get_last_chapter(manga_title)

    def set_last_chapter(self, manga_title: str, chapter: str) -> None:
        """See :meth:`LibraryStore.set_last_chapter`."""
        self.library.set_last_chapter(manga_title, chapter)

    def get_downloaded_chapters(self, manga_title: str) -> List[str]:
        """See :meth:`LibraryStore.get_downloaded`."""
        return self.library.get_downloaded(manga_title)

    def add_downloaded_chapter(self, manga_title: str, chapter: str) -> None:
        """See :meth:`LibraryStore.add_downloaded`."""
        self.library.add_downloaded(manga_title, chapter)

    def is_chapter_downloaded(self, manga_title: str, chapter: str) -> bool:
        """See :meth:`LibraryStore.is_downloaded`."""
        return self.library.is_downloaded(manga_title, chapter)

    def remove_downloaded_chapter(self, manga_title: str, chapter: str) -> bool:
        """See :meth:`LibraryStore.remove_downloaded`."""
        return self.library.remove_downloaded(manga_title, chapter)

    def set_chapter_groups(self, manga_title: str, chapter: str, source: str,
                           group_ids: List[str], group_names: List[str]) -> None:
        """See :meth:`LibraryStore.set_chapter_groups`."""
        self.library.set_chapter_groups(manga_title, chapter, source,
                                        group_ids, group_names)

    def get_chapter_groups(self, manga_title: str, chapter: str) -> Dict[str, Any]:
        """See :meth:`LibraryStore.get_chapter_groups`."""
        return self.library.get_chapter_groups(manga_title, chapter)

    def mark_external_chapter(self, manga_title: str, chapter: str) -> None:
        """See :meth:`LibraryStore.mark_external`."""
        self.library.mark_external(manga_title, chapter)

    def get_external_chapters(self, manga_title: str) -> List[str]:
        """See :meth:`LibraryStore.get_external`."""
        return self.library.get_external(manga_title)

    def is_external_chapter(self, manga_title: str, chapter: str) -> bool:
        """See :meth:`LibraryStore.is_external`."""
        return self.library.is_external(manga_title, chapter)

    def reset_manga_progress(self, manga_title: str, from_chapter: float = 0) -> None:
        """See :meth:`LibraryStore.reset_progress`."""
        self.library.reset_progress(manga_title, from_chapter)

    def rename_manga(self, old_title: str, new_title: str) -> bool:
        """See :meth:`LibraryStore.rename`."""
        return self.library.rename(old_title, new_title)

    def has_manga_history(self, manga_title: str) -> bool:
        """See :meth:`LibraryStore.has_history`."""
        return self.library.has_history(manga_title)

    def remove_manga(self, manga_title: str) -> bool:
        """See :meth:`LibraryStore.remove`."""
        return self.library.remove(manga_title)

    # ── Backup sources and suspicious batches: state.backups ───────────

    def get_pending_backup(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """See :meth:`BackupStore.get_pending`."""
        return self.backups.get_pending(manga_title, chapter)

    def set_pending_backup(self, manga_title: str, chapter: str, backup_source: str,
                           backup_url: str) -> None:
        """See :meth:`BackupStore.set_pending`."""
        self.backups.set_pending(manga_title, chapter, backup_source, backup_url)

    def clear_pending_backup(self, manga_title: str, chapter: str) -> None:
        """See :meth:`BackupStore.clear_pending`."""
        self.backups.clear_pending(manga_title, chapter)

    def clear_all_pending_backups(self, manga_title: str) -> None:
        """See :meth:`BackupStore.clear_all_pending`."""
        self.backups.clear_all_pending(manga_title)

    def get_all_pending_backups(self, manga_title: str) -> Dict[str, Dict[str, Any]]:
        """See :meth:`BackupStore.get_all_pending`."""
        return self.backups.get_all_pending(manga_title)

    def set_suspicious_batch(self, manga_title: str, info: Dict[str, Any]) -> None:
        """See :meth:`BackupStore.set_suspicious_batch`."""
        self.backups.set_suspicious_batch(manga_title, info)

    def get_suspicious_batch(self, manga_title: str) -> Optional[Dict[str, Any]]:
        """See :meth:`BackupStore.get_suspicious_batch`."""
        return self.backups.get_suspicious_batch(manga_title)

    def clear_suspicious_batch(self, manga_title: str) -> None:
        """See :meth:`BackupStore.clear_suspicious_batch`."""
        self.backups.clear_suspicious_batch(manga_title)

    # ── Failed and partial chapters: state.failures ────────────────────

    def add_failed_chapter(
        self,
        manga_title: str,
        chapter: str,
        source: str,
        error: str,
        failed_pages: Optional[List[int]] = None,
    ) -> None:
        """See :meth:`FailureStore.add_failed`."""
        self.failures.add_failed(manga_title, chapter, source, error, failed_pages)

    def get_failed_chapters(self, manga_title: str) -> Dict[str, Any]:
        """See :meth:`FailureStore.get_failed`."""
        return self.failures.get_failed(manga_title)

    def get_all_failed_chapters(self) -> Dict[str, Dict[str, Any]]:
        """See :meth:`FailureStore.get_all_failed`."""
        return self.failures.get_all_failed()

    def clear_failed_chapter(self, manga_title: str, chapter: str) -> None:
        """See :meth:`FailureStore.clear_failed`."""
        self.failures.clear_failed(manga_title, chapter)

    def add_partial_chapter(
        self,
        manga_title: str,
        chapter: str,
        source: str = "",
        failed_pages: Optional[List[int]] = None,
        total_pages: int = 0,
        path: str = "",
        from_backup: bool = False,
    ) -> None:
        """See :meth:`FailureStore.add_partial`."""
        self.failures.add_partial(manga_title, chapter, source, failed_pages,
                                  total_pages, path, from_backup)

    def get_partial_chapters(self, manga_title: str) -> Dict[str, Any]:
        """See :meth:`FailureStore.get_partials`."""
        return self.failures.get_partials(manga_title)

    def get_partial_chapter(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """See :meth:`FailureStore.get_partial`."""
        return self.failures.get_partial(manga_title, chapter)

    def get_all_partial_chapters(self) -> Dict[str, Dict[str, Any]]:
        """See :meth:`FailureStore.get_all_partials`."""
        return self.failures.get_all_partials()

    def clear_partial_chapter(self, manga_title: str, chapter: str) -> None:
        """See :meth:`FailureStore.clear_partial`."""
        self.failures.clear_partial(manga_title, chapter)

    # ── Check history, download history, stats: state.activity ─────────

    def update_last_check(self, new_chapters: int = 0, downloaded: int = 0) -> None:
        """See :meth:`ActivityStore.record_check`."""
        self.activity.record_check(new_chapters, downloaded)

    def get_check_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """See :meth:`ActivityStore.get_check_history`."""
        return self.activity.get_check_history(limit)

    def get_stats(self) -> Dict[str, Any]:
        """See :meth:`ActivityStore.get_stats`."""
        return self.activity.get_stats()

    def add_download_history(self, title: str, chapter: str, fmt: str,
                             path: str = "", size_mb: float = 0, kindle_sent: bool = False,
                             *, source: Optional[str] = None, from_backup: bool = False,
                             partial: bool = False,
                             deleted_after_send: bool = False) -> None:
        """See :meth:`ActivityStore.add_download`."""
        self.activity.add_download(title, chapter, fmt, path, size_mb, kindle_sent,
                                   source=source, from_backup=from_backup,
                                   partial=partial,
                                   deleted_after_send=deleted_after_send)

    def get_download_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """See :meth:`ActivityStore.get_download_history`."""
        return self.activity.get_download_history(limit)

    def remove_download_history(self, manga_title: str) -> int:
        """See :meth:`ActivityStore.remove_downloads`."""
        return self.activity.remove_downloads(manga_title)

    # ── Reading progress, positions, read set: state.reading ───────────

    def set_reading_progress(self, manga_title: str, chapter: str) -> None:
        """See :meth:`ReadingStore.set_progress`."""
        self.reading.set_progress(manga_title, chapter)

    def get_reading_progress(self, manga_title: str) -> Dict[str, Any]:
        """See :meth:`ReadingStore.get_progress`."""
        return self.reading.get_progress(manga_title)

    def get_continue_reading(self) -> Optional[Dict[str, Any]]:
        """See :meth:`ReadingStore.get_continue_reading`."""
        return self.reading.get_continue_reading()

    def set_reader_position(self, manga_title: str, chapter, mode: str,
                            page_index: Optional[int] = None,
                            scroll_ratio: Optional[float] = None) -> None:
        """See :meth:`ReadingStore.set_position`."""
        self.reading.set_position(manga_title, chapter, mode,
                                  page_index=page_index, scroll_ratio=scroll_ratio)

    def get_reader_position(self, manga_title: str, chapter) -> Optional[Dict[str, Any]]:
        """See :meth:`ReadingStore.get_position`."""
        return self.reading.get_position(manga_title, chapter)

    def clear_reader_position(self, manga_title: str, chapter) -> None:
        """See :meth:`ReadingStore.clear_position`."""
        self.reading.clear_position(manga_title, chapter)

    def mark_chapter_read(self, manga_title: str, chapter) -> None:
        """See :meth:`ReadingStore.mark_read`."""
        self.reading.mark_read(manga_title, chapter)

    def unmark_chapter_read(self, manga_title: str, chapter) -> None:
        """See :meth:`ReadingStore.unmark_read`."""
        self.reading.unmark_read(manga_title, chapter)

    def is_chapter_read(self, manga_title: str, chapter) -> bool:
        """See :meth:`ReadingStore.is_read`."""
        return self.reading.is_read(manga_title, chapter)

    def get_read_chapters(self, manga_title: str) -> List[str]:
        """See :meth:`ReadingStore.get_read`."""
        return self.reading.get_read(manga_title)

    def get_read_count(self, manga_title: str) -> int:
        """See :meth:`ReadingStore.get_read_count`."""
        return self.reading.get_read_count(manga_title)

    # ── Available chapters, baseline, badges: state.catalogue ──────────

    def set_new_chapters(self, manga_title: str, count: int) -> None:
        """See :meth:`CatalogueStore.set_new_count`."""
        self.catalogue.set_new_count(manga_title, count)

    def get_new_chapters(self, manga_title: str) -> int:
        """See :meth:`CatalogueStore.get_new_count`."""
        return self.catalogue.get_new_count(manga_title)

    def clear_new_chapters(self, manga_title: str) -> None:
        """See :meth:`CatalogueStore.clear_new_count`."""
        self.catalogue.clear_new_count(manga_title)

    def decrement_new_chapters(self, manga_title: str) -> None:
        """See :meth:`CatalogueStore.decrement_new_count`."""
        self.catalogue.decrement_new_count(manga_title)

    def set_available_chapters(self, manga_title: str,
                               chapters: List[Dict[str, Any]]) -> None:
        """See :meth:`CatalogueStore.set_available`."""
        self.catalogue.set_available(manga_title, chapters)

    def get_available_chapters(self, manga_title: str) -> List[Dict[str, Any]]:
        """See :meth:`CatalogueStore.get_available`."""
        return self.catalogue.get_available(manga_title)

    def get_available_chapter_count(self, manga_title: str) -> int:
        """See :meth:`CatalogueStore.get_available_count`."""
        return self.catalogue.get_available_count(manga_title)

    def get_catalogue_baseline(self, manga_title: str) -> Optional[float]:
        """See :meth:`CatalogueStore.get_baseline`."""
        return self.catalogue.get_baseline(manga_title)

    def set_catalogue_baseline(self, manga_title: str, highest: float) -> None:
        """See :meth:`CatalogueStore.set_baseline`."""
        self.catalogue.set_baseline(manga_title, highest)

    # ── Notifications: state.notifications ─────────────────────────────

    def add_notification(self, ntype: str, message: str,
                         details: Optional[str] = None) -> None:
        """See :meth:`NotificationStore.add`."""
        self.notifications.add(ntype, message, details)

    def get_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """See :meth:`NotificationStore.get_recent`."""
        return self.notifications.get_recent(limit)

    def get_unread_count(self) -> int:
        """See :meth:`NotificationStore.get_unread_count`."""
        return self.notifications.get_unread_count()

    def mark_notifications_read(self) -> None:
        """See :meth:`NotificationStore.mark_all_read`."""
        self.notifications.mark_all_read()

    def clear_notifications(self) -> None:
        """See :meth:`NotificationStore.clear`."""
        self.notifications.clear()

    def filter_notifications(self, kind: str, limit: int = 100) -> List[Dict[str, Any]]:
        """See :meth:`NotificationStore.filter`."""
        return self.notifications.filter(kind, limit)

    # ── Search history: state.searches ─────────────────────────────────

    def add_search_query(self, query: str, limit: int = 8) -> None:
        """See :meth:`SearchHistoryStore.add`."""
        self.searches.add(query, limit)

    def get_recent_searches(self, limit: int = 8) -> List[str]:
        """See :meth:`SearchHistoryStore.get_recent`."""
        return self.searches.get_recent(limit)

    def clear_search_history(self) -> None:
        """See :meth:`SearchHistoryStore.clear`."""
        self.searches.clear()

    # ── Source health: state.source_health ─────────────────────────────

    def update_source_health(self, domain: str, success: bool,
                             error_msg: str = "", latency_ms: Optional[int] = None) -> None:
        """See :meth:`SourceHealthStore.update`."""
        self.source_health.update(domain, success, error_msg, latency_ms)

    def get_source_health(self, domain: str) -> Dict[str, Any]:
        """See :meth:`SourceHealthStore.get`."""
        return self.source_health.get(domain)

    def get_all_source_health(self) -> Dict[str, Dict[str, Any]]:
        """See :meth:`SourceHealthStore.get_all`."""
        return self.source_health.get_all()
