"""
State management for MeManga - tracks downloaded chapters and check history
"""

import copy
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any


_LEADING_CHAPTER_RE = re.compile(r"\s*(\d+(?:\.\d+)?)")


def _leading_chapter_number(label: Any) -> Optional[float]:
    """Return the leading numeric chapter value, if the label starts with one."""
    match = _LEADING_CHAPTER_RE.match(str(label))
    if not match:
        return None
    return float(match.group(1))


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
    """

    # Latency above which a successful probe is flagged "warning" instead
    # of "ok". Healthy sites on an ordinary connection routinely answer in
    # 500-2000 ms, so a lower bound paints almost every source yellow. This
    # threshold reserves the warning tier for responses that are genuinely
    # sluggish.
    SLOW_LATENCY_MS = 2500

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".config" / "memanga"

        self.state_path = self.config_dir / "state.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Reentrant so mutators that persist immediately can call save()
        # (and nested public getters) while already holding the lock.
        self._lock = threading.RLock()
        self._dirty = False
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load state from file."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return self._default_state()
        return self._default_state()

    def _default_state(self) -> Dict[str, Any]:
        """Return default state structure."""
        return {
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
        passes in) aliases ``_data`` — shallow copies still leaked the
        dicts nested inside returned lists, e.g. editing a row from
        get_available_chapters() changed stored state. Everything in
        ``_data`` is plain JSON types, so deepcopy stays cheap relative
        to the GUI work that consumes these snapshots.
        """
        return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

    @classmethod
    def _copy_entry(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Snapshot a manga entry, deep-copying its container values."""
        return {k: cls._snapshot(v) for k, v in entry.items()}

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

    def save(self):
        """Save state to file atomically. Thread-safe."""
        with self._lock:
            data_snapshot = json.dumps(self._data, indent=None, default=str)
            fd, tmp_path = tempfile.mkstemp(dir=self.config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(data_snapshot)
                os.replace(tmp_path, self.state_path)
                self._dirty = False
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

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

    @staticmethod
    def _chapter_sort_key(chapter):
        try:
            return float(chapter)
        except (TypeError, ValueError):
            return 0.0

    def merge_missing_manga_state(
        self,
        imported_state: Dict[str, Any],
        *,
        merge_existing_downloaded: bool = False,
    ):
        """Merge imported manga state entries without replacing local state.

        Issue #110: Settings backup import used to build a snapshot with
        get("manga"), mutate it, then set("manga") wholesale. A worker update
        between those calls could be overwritten. Keep the read/merge/save under
        the State lock so local worker mutations serialize with import.
        """
        if imported_state is None:
            imported_state = {}
        if not isinstance(imported_state, dict):
            raise TypeError("imported_state must be a dict")
        with self._locked() as data:
            manga = data.setdefault("manga", {})
            for title, state_data in imported_state.items():
                if title in manga and merge_existing_downloaded:
                    entry = manga[title]
                    if not isinstance(entry, dict):
                        entry = {}
                        manga[title] = entry
                    if isinstance(state_data, dict):
                        existing_downloaded = set(entry.get("downloaded", []))
                        imported_downloaded = set(state_data.get("downloaded", []))
                        entry["downloaded"] = sorted(
                            existing_downloaded | imported_downloaded,
                            key=self._chapter_sort_key,
                        )
                elif not manga.get(title):
                    manga[title] = self._snapshot(state_data)
            self.save()

    # ========================================================================
    # Manga State
    # ========================================================================

    def get_manga_state(self, manga_title: str) -> Dict[str, Any]:
        """Get full state for a manga (a snapshot, not the live entry)."""
        with self._locked() as data:
            return self._copy_entry(data.get("manga", {}).get(manga_title, {}))

    def get_last_chapter(self, manga_title: str) -> Optional[str]:
        """Get the last downloaded chapter number for a manga."""
        return self._entry_value(manga_title, "last_chapter")

    def set_last_chapter(self, manga_title: str, chapter: str):
        """Set the last downloaded chapter for a manga.

        Marks dirty rather than syncing — the app's 5s flush timer + the
        closeEvent flush cover durability without thrashing disk on
        every per-chapter update.
        """
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["last_chapter"] = chapter
            data["manga"][manga_title]["last_updated"] = datetime.now().isoformat()
            self._mark_dirty()

    def get_downloaded_chapters(self, manga_title: str) -> List[str]:
        """Get list of all downloaded chapter numbers for a manga."""
        return self._entry_value(manga_title, "downloaded", [])

    def add_downloaded_chapter(self, manga_title: str, chapter: str):
        """Mark a chapter as downloaded."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]

            if "downloaded" not in entry:
                entry["downloaded"] = []

            chapter_str = str(chapter)
            if chapter_str not in entry["downloaded"]:
                entry["downloaded"].append(chapter_str)
                def _sort_key(x):
                    num = _leading_chapter_number(x)
                    return num if num is not None else 0.0
                entry["downloaded"].sort(key=_sort_key)

            entry["last_chapter"] = chapter_str
            entry["last_updated"] = datetime.now().isoformat()
            self._mark_dirty()

    def is_chapter_downloaded(self, manga_title: str, chapter: str) -> bool:
        """Check if a chapter has been downloaded."""
        return str(chapter) in self.get_downloaded_chapters(manga_title)

    # ========================================================================
    # Backup Source Tracking
    # ========================================================================

    def get_pending_backup(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """Get pending backup info for a chapter (if waiting for primary to catch up)."""
        pending = self._entry_value(manga_title, "pending_backup", {})
        return pending.get(str(chapter))

    def set_pending_backup(self, manga_title: str, chapter: str, backup_source: str, backup_url: str):
        """Mark a chapter as seen on backup source, start the waiting period."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]

            if "pending_backup" not in entry:
                entry["pending_backup"] = {}

            chapter_str = str(chapter)
            if chapter_str not in entry["pending_backup"]:
                entry["pending_backup"][chapter_str] = {
                    "first_seen": datetime.now().isoformat(),
                    "backup_source": backup_source,
                    "backup_url": backup_url,
                }
                self.save()

    def clear_pending_backup(self, manga_title: str, chapter: str):
        """Clear pending backup for a chapter (downloaded from primary or backup)."""
        with self._locked() as data:
            pending = data.get("manga", {}).get(manga_title, {}).get("pending_backup", {})

            chapter_str = str(chapter)
            if chapter_str in pending:
                del pending[chapter_str]
                self.save()

    def clear_all_pending_backups(self, manga_title: str):
        """Clear all pending backups for a manga."""
        with self._locked() as data:
            if manga_title in data.get("manga", {}):
                data["manga"][manga_title]["pending_backup"] = {}
                self.save()

    def get_all_pending_backups(self, manga_title: str) -> Dict[str, Dict[str, Any]]:
        """Get all pending backup chapters for a manga."""
        return self._entry_value(manga_title, "pending_backup", {})

    # ========================================================================
    # Suspicious Batch Tracking
    # ========================================================================

    def set_suspicious_batch(self, manga_title: str, info: Dict[str, Any]):
        """Record a suspicious chapter batch that was held back from
        download/delivery. ``info`` should describe the batch (chapters,
        score, reasons, backup verification status, detected_at)."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["suspicious_batch"] = self._snapshot(info)
            self.save()

    def get_suspicious_batch(self, manga_title: str) -> Optional[Dict[str, Any]]:
        """Get the held-back suspicious batch for a manga, if any."""
        return self._entry_value(manga_title, "suspicious_batch")

    def clear_suspicious_batch(self, manga_title: str):
        """Clear the suspicious batch record (accepted, confirmed, or stale)."""
        with self._locked() as data:
            manga_state = data.get("manga", {}).get(manga_title, {})
            if "suspicious_batch" in manga_state:
                del manga_state["suspicious_batch"]
                self.save()

    # ========================================================================
    # Failed Chapter Tracking
    # ========================================================================

    def add_failed_chapter(
        self,
        manga_title: str,
        chapter: str,
        source: str,
        error: str,
        failed_pages: Optional[List[int]] = None,
    ):
        """Record a chapter download failure."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            chapter_str = str(chapter)
            entry = data["manga"][manga_title]

            if "failed_chapters" not in entry:
                entry["failed_chapters"] = {}

            existing = entry["failed_chapters"].get(chapter_str, {})
            entry["failed_chapters"][chapter_str] = {
                "failed_at": datetime.now().isoformat(),
                "source": source,
                "error": error[:300],
                "failed_pages": self._snapshot(failed_pages or []),
                "attempts": existing.get("attempts", 0) + 1,
            }
            self.save()

    def get_failed_chapters(self, manga_title: str) -> Dict[str, Any]:
        """Get all failed chapter records for a manga."""
        return self._entry_value(manga_title, "failed_chapters", {})

    def get_all_failed_chapters(self) -> Dict[str, Dict[str, Any]]:
        """Get failed chapters for all manga that have failures."""
        with self._locked() as data:
            result = {}
            for title, manga_state in data.get("manga", {}).items():
                failed = manga_state.get("failed_chapters", {})
                if failed:
                    result[title] = copy.deepcopy(failed)
            return result

    def clear_failed_chapter(self, manga_title: str, chapter: str):
        """Remove a failed chapter record after successful re-download."""
        with self._locked() as data:
            chapter_str = str(chapter)
            failed = data.get("manga", {}).get(manga_title, {}).get("failed_chapters", {})
            if chapter_str in failed:
                del failed[chapter_str]
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
            }

    # ========================================================================
    # Check History
    # ========================================================================

    def update_last_check(self, new_chapters: int = 0, downloaded: int = 0):
        """Update the last check timestamp and optionally log to history."""
        with self._locked() as data:
            now = datetime.now().isoformat()
            data["last_check"] = now

            # Add to history (keep last 50)
            if "check_history" not in data:
                data["check_history"] = []

            data["check_history"].append({
                "timestamp": now,
                "new_chapters": new_chapters,
                "downloaded": downloaded,
            })

            # Trim history
            data["check_history"] = data["check_history"][-50:]

            self.save()

    def get_check_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent check history."""
        with self._locked() as data:
            return self._snapshot(data.get("check_history", [])[-limit:])

    # ========================================================================
    # Statistics
    # ========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        with self._locked() as data:
            manga_data = data.get("manga", {})

            total_manga = len(manga_data)
            total_chapters = sum(
                len(m.get("downloaded", []))
                for m in manga_data.values()
            )

            return {
                "total_manga": total_manga,
                "total_chapters": total_chapters,
                "last_check": data.get("last_check"),
                "checks_logged": len(data.get("check_history", [])),
            }

    # ========================================================================
    # Reading Progress
    # ========================================================================

    def set_reading_progress(self, manga_title: str, chapter: str):
        """Update the last-read chapter for a manga."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if "reading_progress" not in entry:
                entry["reading_progress"] = {}
            entry["reading_progress"]["last_chapter"] = str(chapter)
            entry["reading_progress"]["last_read"] = datetime.now().isoformat()
            self._mark_dirty()

    def get_reading_progress(self, manga_title: str) -> Dict[str, Any]:
        """Get reading progress for a manga."""
        return self._entry_value(manga_title, "reading_progress", {})

    def get_continue_reading(self) -> Optional[Dict[str, Any]]:
        """Get the most recently read manga for 'Continue Reading' widget."""
        with self._locked() as data:
            best = None
            best_time = None
            for title, entry in data.get("manga", {}).items():
                progress = entry.get("reading_progress", {})
                last_read = progress.get("last_read")
                if last_read and progress.get("last_chapter"):
                    if best_time is None or last_read > best_time:
                        best_time = last_read
                        best = {"title": title, **progress}
            return self._snapshot(best)

    # ── Per-chapter read tracking (issue #18) ──────────────────────────
    # `reading_progress.last_chapter` only tracks the cursor (the most-
    # recently-opened chapter). The set below tracks every individual
    # chapter the user has opened in the Reader, so the Library card and
    # Detail chapter rows can show a per-chapter read indicator.

    def mark_chapter_read(self, manga_title: str, chapter):
        """Add `chapter` to the per-manga read set (idempotent)."""
        if chapter is None or str(chapter).strip() == "":
            return
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            read_list = entry.setdefault("read_chapters", [])
            ch = str(chapter)
            if ch not in read_list:
                read_list.append(ch)
                self._mark_dirty()

    def unmark_chapter_read(self, manga_title: str, chapter):
        with self._locked() as data:
            entry = data.get("manga", {}).get(manga_title)
            if not entry:
                return
            read_list = entry.get("read_chapters", [])
            ch = str(chapter)
            if ch in read_list:
                read_list.remove(ch)
                self._mark_dirty()

    def is_chapter_read(self, manga_title: str, chapter) -> bool:
        return str(chapter) in self.get_read_chapters(manga_title)

    def get_read_chapters(self, manga_title: str) -> List[str]:
        return self._entry_value(manga_title, "read_chapters", []) or []

    def get_read_count(self, manga_title: str) -> int:
        return len(self.get_read_chapters(manga_title))

    # ========================================================================
    # New Chapter Badges
    # ========================================================================

    def set_new_chapters(self, manga_title: str, count: int):
        """Set the number of new chapters available for a manga."""
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["new_chapters_available"] = count
            self._mark_dirty()

    def get_new_chapters(self, manga_title: str) -> int:
        """Get the number of new chapters available."""
        return self._entry_value(manga_title, "new_chapters_available", 0)

    def clear_new_chapters(self, manga_title: str):
        """Clear the new chapters badge (e.g. after downloading)."""
        with self._locked() as data:
            entry = data.get("manga", {}).get(manga_title, {})
            if entry.get("new_chapters_available", 0) > 0:
                entry["new_chapters_available"] = 0
                self._mark_dirty()

    def decrement_new_chapters(self, manga_title: str):
        """Decrement the new chapters badge by 1 (used by manual single downloads)."""
        with self._locked() as data:
            entry = data.get("manga", {}).get(manga_title, {})
            current = entry.get("new_chapters_available", 0)
            if current > 0:
                entry["new_chapters_available"] = current - 1
                self._mark_dirty()

    # ========================================================================
    # Available Chapters Cache
    # ========================================================================

    def set_available_chapters(self, manga_title: str, chapters: List[Dict[str, Any]]):
        """Cache the full list of chapters from the last check (for both modes).

        Each entry should contain: number, title, source, source_url, is_backup.
        Used by the Detail page to show every chapter as 'Read' (downloaded) or
        'Download' (available) without re-scraping.
        """
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["available_chapters"] = self._snapshot(list(chapters))
            self._mark_dirty()

    def get_available_chapters(self, manga_title: str) -> List[Dict[str, Any]]:
        """Get the cached chapter list for a manga (empty list if never checked)."""
        return self._entry_value(manga_title, "available_chapters", [])

    # ========================================================================
    # External Chapters (already read outside the app)
    # ========================================================================

    def mark_external_chapter(self, manga_title: str, chapter: str):
        """Record a chapter that was read outside MeManga.

        Stored separately from `downloaded` so the app never lies about what's
        on disk; the Detail page renders these as "Read elsewhere" rows.
        """
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if "external_chapters" not in entry:
                entry["external_chapters"] = []
            ch_str = str(chapter)
            if ch_str not in entry["external_chapters"]:
                entry["external_chapters"].append(ch_str)

                def _sort_key(x):
                    num = _leading_chapter_number(x)
                    return num if num is not None else 0.0

                entry["external_chapters"].sort(key=_sort_key)
                self._mark_dirty()

    def get_external_chapters(self, manga_title: str) -> List[str]:
        """Get the chapters the user marked as already read elsewhere."""
        return self._entry_value(manga_title, "external_chapters", [])

    def is_external_chapter(self, manga_title: str, chapter: str) -> bool:
        """Whether a chapter was previously marked as read-elsewhere."""
        return str(chapter) in self.get_external_chapters(manga_title)

    # ========================================================================
    # Notifications
    # ========================================================================

    def add_notification(self, ntype: str, message: str):
        """Add a notification to the log."""
        with self._locked() as data:
            if "notifications" not in data:
                data["notifications"] = []
            data["notifications"].append({
                "type": ntype,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "read": False,
            })
            data["notifications"] = data["notifications"][-100:]
            self._mark_dirty()

    def get_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent notifications. Items are copies — mark_notifications_read
        mutates the stored dicts in place, so live references would race."""
        with self._locked() as data:
            return self._snapshot(
                list(reversed(data.get("notifications", [])[-limit:])))

    def get_unread_count(self) -> int:
        """Count unread notifications."""
        with self._locked() as data:
            return sum(1 for n in data.get("notifications", []) if not n.get("read"))

    def mark_notifications_read(self):
        """Mark all notifications as read."""
        with self._locked() as data:
            for n in data.get("notifications", []):
                n["read"] = True
            self._mark_dirty()

    def clear_notifications(self):
        """Wipe all notifications. Used by the GUI's 'Clear all' button."""
        with self._locked() as data:
            data["notifications"] = []
            self._mark_dirty()

    def filter_notifications(self, kind: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return notifications filtered by category.

        Categories collapse the granular `type` values into the four chip
        buckets used in the UI:
            all       — everything
            new       — new-chapter findings ("check")
            downloads — download-complete / kindle-sent events
            system    — errors, warnings, generic system events
        """
        with self._locked() as data:
            all_notifs = self._snapshot(
                list(reversed(data.get("notifications", [])[-limit:])))
        if kind == "all":
            return all_notifs
        bucket_map = {
            "new":       {"check"},
            "downloads": {"download", "kindle"},
            "system":    {"error", "warn", "system"},
        }
        targets = bucket_map.get(kind, set())
        return [n for n in all_notifs if n.get("type") in targets]

    # ========================================================================
    # Search history (for Search page recent-chip row)
    # ========================================================================

    def add_search_query(self, query: str, limit: int = 8):
        """Push a query onto the deduped recent-search list (newest first)."""
        if not query or not query.strip():
            return
        q = query.strip()
        with self._locked() as data:
            history = data.get("search_history", []) or []
            # Dedupe by case-insensitive match, then prepend.
            history = [h for h in history if h.lower() != q.lower()]
            history.insert(0, q)
            data["search_history"] = history[:limit]
            self._mark_dirty()

    def get_recent_searches(self, limit: int = 8) -> List[str]:
        with self._locked() as data:
            return list(data.get("search_history", []) or [])[:limit]

    def clear_search_history(self):
        with self._locked() as data:
            data["search_history"] = []
            self._mark_dirty()

    # ========================================================================
    # Download History
    # ========================================================================

    def add_download_history(self, title: str, chapter: str, fmt: str,
                             path: str = "", size_mb: float = 0, kindle_sent: bool = False):
        """Log a completed download."""
        with self._locked() as data:
            if "download_history" not in data:
                data["download_history"] = []
            data["download_history"].append({
                "title": title,
                "chapter": chapter,
                "format": fmt,
                "path": path,
                "size_mb": round(size_mb, 2),
                "kindle_sent": kindle_sent,
                "timestamp": datetime.now().isoformat(),
            })
            data["download_history"] = data["download_history"][-200:]
            self._mark_dirty()

    def get_download_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent download history."""
        with self._locked() as data:
            return self._snapshot(
                list(reversed(data.get("download_history", [])[-limit:])))

    # ========================================================================
    # Source Health
    # ========================================================================

    def update_source_health(self, domain: str, success: bool,
                             error_msg: str = "", latency_ms: int = None):
        """Update health status for a source domain.

        ``latency_ms`` (optional) records the round-trip time of the
        probe that produced this status update. Drives the "Xms" badge
        in the Sources screen.
        """
        with self._locked() as data:
            if "source_health" not in data:
                data["source_health"] = {}
            now = datetime.now().isoformat()
            health = data["source_health"].get(domain, {"error_count": 0})
            if success:
                health["last_success"] = now
                health["error_count"] = 0
                # Flag only genuinely slow responses; see SLOW_LATENCY_MS.
                if latency_ms is not None and latency_ms > self.SLOW_LATENCY_MS:
                    health["status"] = "warning"
                else:
                    health["status"] = "ok"
            else:
                health["last_error"] = now
                health["last_error_msg"] = error_msg[:100]
                health["error_count"] = health.get("error_count", 0) + 1
                health["status"] = "warning" if health["error_count"] < 3 else "error"
            if latency_ms is not None:
                health["latency_ms"] = int(latency_ms)
            data["source_health"][domain] = health
            self._mark_dirty()

    def get_source_health(self, domain: str) -> Dict[str, Any]:
        """Get health info for a source."""
        with self._locked() as data:
            return self._snapshot(data.get("source_health", {}).get(domain, {}))

    def get_all_source_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health info for all sources. Entries are copies — probes
        update the stored dicts in place."""
        with self._locked() as data:
            return self._snapshot(data.get("source_health", {}))

    def reset_manga_progress(self, manga_title: str, from_chapter: float = 0):
        """Reset a manga's download progress to re-download from a specific chapter.
        If from_chapter is 0, clears everything for a full re-download.
        If from_chapter is N, keeps chapters < N downloaded and re-downloads N onwards.
        """
        with self._locked() as data:
            self._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if from_chapter == 0:
                entry["last_chapter"] = None
                entry["downloaded"] = []
            else:
                # Keep only chapters before from_chapter, remove the rest.
                # Part-style labels (e.g. "3 Part 1") compare by their leading
                # chapter number. Labels with no leading number are preserved
                # because they cannot be ordered safely against the threshold.
                def _keep_downloaded(ch):
                    num = _leading_chapter_number(ch)
                    return num is None or num < from_chapter

                entry["downloaded"] = [
                    ch for ch in entry.get("downloaded", [])
                    if _keep_downloaded(ch)
                ]
                entry["last_chapter"] = None
            entry["last_updated"] = datetime.now().isoformat()
            self.save()

    # ========================================================================
    # Cleanup
    # ========================================================================

    def rename_manga(self, old_title: str, new_title: str) -> bool:
        """Move a manga's state entry to a new title (edit/rename flows).

        Issue #110: replaces the GUI's direct ``_data`` pokes so renames go
        through the lock like every other mutation.
        """
        with self._locked() as data:
            manga = data.get("manga", {})
            if old_title not in manga:
                return False
            manga[new_title] = manga.pop(old_title)
            self.save()
            return True

    def remove_manga(self, manga_title: str) -> bool:
        """Remove a manga from state."""
        with self._locked() as data:
            if manga_title in data.get("manga", {}):
                del data["manga"][manga_title]
                self.save()
                return True
            return False

    def clear_all(self):
        """Clear all state (fresh start)."""
        with self._lock:
            self._data = self._default_state()
            self.save()
