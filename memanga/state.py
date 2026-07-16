"""
State management for MeManga - tracks downloaded chapters and check history
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any


class State:
    """Manages state file (tracking what's been downloaded).

    Uses a dirty flag and thread lock to batch saves and prevent corruption.
    Call flush() explicitly when you need the file written immediately.
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
        self._lock = threading.Lock()
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
    
    def save(self):
        """Save state to file atomically. Thread-safe."""
        with self._lock:
            self._dirty = False
            data_snapshot = json.dumps(self._data, indent=None, default=str)

        fd, tmp_path = tempfile.mkstemp(dir=self.config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data_snapshot)
            os.replace(tmp_path, self.state_path)
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
        if self._dirty:
            self.save()

    def get(self, key: str, default=None):
        """Get a state value."""
        return self._data.get(key, default)

    def set(self, key: str, value):
        """Set a state value and save immediately."""
        self._data[key] = value
        self.save()
    
    # ========================================================================
    # Manga State
    # ========================================================================
    
    def get_manga_state(self, manga_title: str) -> Dict[str, Any]:
        """Get full state for a manga."""
        return self._data.get("manga", {}).get(manga_title, {})
    
    def get_last_chapter(self, manga_title: str) -> Optional[str]:
        """Get the last downloaded chapter number for a manga."""
        manga_state = self.get_manga_state(manga_title)
        return manga_state.get("last_chapter")
    
    def set_last_chapter(self, manga_title: str, chapter: str):
        """Set the last downloaded chapter for a manga.

        Marks dirty rather than syncing — the app's 5s flush timer + the
        closeEvent flush cover durability without thrashing disk on
        every per-chapter update.
        """
        self._ensure_manga_entry(manga_title)
        self._data["manga"][manga_title]["last_chapter"] = chapter
        self._data["manga"][manga_title]["last_updated"] = datetime.now().isoformat()
        self._mark_dirty()
    
    def get_downloaded_chapters(self, manga_title: str) -> List[str]:
        """Get list of all downloaded chapter numbers for a manga."""
        manga_state = self.get_manga_state(manga_title)
        return manga_state.get("downloaded", [])
    
    def add_downloaded_chapter(self, manga_title: str, chapter: str):
        """Mark a chapter as downloaded."""
        self._ensure_manga_entry(manga_title)
        
        if "downloaded" not in self._data["manga"][manga_title]:
            self._data["manga"][manga_title]["downloaded"] = []
        
        chapter_str = str(chapter)
        if chapter_str not in self._data["manga"][manga_title]["downloaded"]:
            self._data["manga"][manga_title]["downloaded"].append(chapter_str)
            def _sort_key(x):
                try:
                    return float(x)
                except (ValueError, TypeError):
                    return 0.0
            self._data["manga"][manga_title]["downloaded"].sort(key=_sort_key)
        
        self._data["manga"][manga_title]["last_chapter"] = chapter_str
        self._data["manga"][manga_title]["last_updated"] = datetime.now().isoformat()
        self._mark_dirty()

    def is_chapter_downloaded(self, manga_title: str, chapter: str) -> bool:
        """Check if a chapter has been downloaded."""
        return str(chapter) in self.get_downloaded_chapters(manga_title)
    
    # ========================================================================
    # Backup Source Tracking
    # ========================================================================
    
    def get_pending_backup(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """Get pending backup info for a chapter (if waiting for primary to catch up)."""
        manga_state = self.get_manga_state(manga_title)
        pending = manga_state.get("pending_backup", {})
        return pending.get(str(chapter))
    
    def set_pending_backup(self, manga_title: str, chapter: str, backup_source: str, backup_url: str):
        """Mark a chapter as seen on backup source, start the waiting period."""
        self._ensure_manga_entry(manga_title)
        
        if "pending_backup" not in self._data["manga"][manga_title]:
            self._data["manga"][manga_title]["pending_backup"] = {}
        
        chapter_str = str(chapter)
        if chapter_str not in self._data["manga"][manga_title]["pending_backup"]:
            self._data["manga"][manga_title]["pending_backup"][chapter_str] = {
                "first_seen": datetime.now().isoformat(),
                "backup_source": backup_source,
                "backup_url": backup_url,
            }
            self.save()
    
    def clear_pending_backup(self, manga_title: str, chapter: str):
        """Clear pending backup for a chapter (downloaded from primary or backup)."""
        manga_state = self.get_manga_state(manga_title)
        pending = manga_state.get("pending_backup", {})
        
        chapter_str = str(chapter)
        if chapter_str in pending:
            del self._data["manga"][manga_title]["pending_backup"][chapter_str]
            self.save()
    
    def clear_all_pending_backups(self, manga_title: str):
        """Clear all pending backups for a manga."""
        if manga_title in self._data.get("manga", {}):
            self._data["manga"][manga_title]["pending_backup"] = {}
            self.save()
    
    def get_all_pending_backups(self, manga_title: str) -> Dict[str, Dict[str, Any]]:
        """Get all pending backup chapters for a manga."""
        manga_state = self.get_manga_state(manga_title)
        return manga_state.get("pending_backup", {})
    
    # ========================================================================
    # Suspicious Batch Tracking
    # ========================================================================

    def set_suspicious_batch(self, manga_title: str, info: Dict[str, Any]):
        """Record a suspicious chapter batch that was held back from
        download/delivery. ``info`` should describe the batch (chapters,
        score, reasons, backup verification status, detected_at)."""
        self._ensure_manga_entry(manga_title)
        self._data["manga"][manga_title]["suspicious_batch"] = info
        self.save()

    def get_suspicious_batch(self, manga_title: str) -> Optional[Dict[str, Any]]:
        """Get the held-back suspicious batch for a manga, if any."""
        return self.get_manga_state(manga_title).get("suspicious_batch")

    def clear_suspicious_batch(self, manga_title: str):
        """Clear the suspicious batch record (accepted, confirmed, or stale)."""
        manga_state = self._data.get("manga", {}).get(manga_title, {})
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
        self._ensure_manga_entry(manga_title)
        chapter_str = str(chapter)

        if "failed_chapters" not in self._data["manga"][manga_title]:
            self._data["manga"][manga_title]["failed_chapters"] = {}

        existing = self._data["manga"][manga_title]["failed_chapters"].get(chapter_str, {})
        self._data["manga"][manga_title]["failed_chapters"][chapter_str] = {
            "failed_at": datetime.now().isoformat(),
            "source": source,
            "error": error[:300],
            "failed_pages": failed_pages or [],
            "attempts": existing.get("attempts", 0) + 1,
        }
        self.save()

    def get_failed_chapters(self, manga_title: str) -> Dict[str, Any]:
        """Get all failed chapter records for a manga."""
        manga_state = self.get_manga_state(manga_title)
        return manga_state.get("failed_chapters", {})

    def get_all_failed_chapters(self) -> Dict[str, Dict[str, Any]]:
        """Get failed chapters for all manga that have failures."""
        result = {}
        for title, manga_state in self._data.get("manga", {}).items():
            failed = manga_state.get("failed_chapters", {})
            if failed:
                result[title] = failed
        return result

    def clear_failed_chapter(self, manga_title: str, chapter: str):
        """Remove a failed chapter record after successful re-download."""
        chapter_str = str(chapter)
        failed = self._data.get("manga", {}).get(manga_title, {}).get("failed_chapters", {})
        if chapter_str in failed:
            del self._data["manga"][manga_title]["failed_chapters"][chapter_str]
            self.save()

    def _ensure_manga_entry(self, manga_title: str):
        """Ensure manga entry exists in state."""
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
        now = datetime.now().isoformat()
        self._data["last_check"] = now
        
        # Add to history (keep last 50)
        if "check_history" not in self._data:
            self._data["check_history"] = []
        
        self._data["check_history"].append({
            "timestamp": now,
            "new_chapters": new_chapters,
            "downloaded": downloaded,
        })
        
        # Trim history
        self._data["check_history"] = self._data["check_history"][-50:]
        
        self.save()
    
    def get_check_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent check history."""
        history = self._data.get("check_history", [])
        return history[-limit:]
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        manga_data = self._data.get("manga", {})
        
        total_manga = len(manga_data)
        total_chapters = sum(
            len(m.get("downloaded", []))
            for m in manga_data.values()
        )
        
        return {
            "total_manga": total_manga,
            "total_chapters": total_chapters,
            "last_check": self._data.get("last_check"),
            "checks_logged": len(self._data.get("check_history", [])),
        }
    
    # ========================================================================
    # Reading Progress
    # ========================================================================

    def set_reading_progress(self, manga_title: str, chapter: str):
        """Update the last-read chapter for a manga."""
        self._ensure_manga_entry(manga_title)
        entry = self._data["manga"][manga_title]
        if "reading_progress" not in entry:
            entry["reading_progress"] = {}
        entry["reading_progress"]["last_chapter"] = str(chapter)
        entry["reading_progress"]["last_read"] = datetime.now().isoformat()
        self._mark_dirty()

    def get_reading_progress(self, manga_title: str) -> Dict[str, Any]:
        """Get reading progress for a manga."""
        return self.get_manga_state(manga_title).get("reading_progress", {})

    def get_continue_reading(self) -> Optional[Dict[str, Any]]:
        """Get the most recently read manga for 'Continue Reading' widget."""
        best = None
        best_time = None
        for title, data in self._data.get("manga", {}).items():
            progress = data.get("reading_progress", {})
            last_read = progress.get("last_read")
            if last_read and progress.get("last_chapter"):
                if best_time is None or last_read > best_time:
                    best_time = last_read
                    best = {"title": title, **progress}
        return best

    # ── Reader resume position (issue #106) ────────────────────────────
    # Separate from `reading_progress.last_chapter` (the cursor) and
    # `read_chapters` (the read set): this stores *where inside a chapter*
    # the reader left off, so reopening a chapter can restore the exact
    # page (paged mode) or scroll offset (webtoon/strip mode).

    def set_reader_position(self, manga_title: str, chapter, mode: str,
                            page_index: Optional[int] = None,
                            scroll_ratio: Optional[float] = None):
        """Save the in-chapter resume position for a manga/chapter."""
        if chapter is None or str(chapter).strip() == "":
            return
        self._ensure_manga_entry(manga_title)
        entry = self._data["manga"][manga_title]
        positions = entry.setdefault("reader_positions", {})
        pos: Dict[str, Any] = {
            "mode": mode,
            "updated_at": datetime.now().isoformat(),
        }
        if page_index is not None:
            pos["page_index"] = max(0, int(page_index))
        if scroll_ratio is not None:
            pos["scroll_ratio"] = min(1.0, max(0.0, float(scroll_ratio)))
        positions[str(chapter)] = pos
        self._mark_dirty()

    def get_reader_position(self, manga_title: str, chapter) -> Optional[Dict[str, Any]]:
        """Get the saved resume position, or None if never saved."""
        positions = self.get_manga_state(manga_title).get("reader_positions", {})
        return positions.get(str(chapter))

    def clear_reader_position(self, manga_title: str, chapter):
        """Drop the saved resume position (e.g. chapter finished)."""
        positions = self._data.get("manga", {}).get(manga_title, {}).get("reader_positions", {})
        ch = str(chapter)
        if ch in positions:
            del positions[ch]
            self._mark_dirty()

    # ── Per-chapter read tracking (issue #18) ──────────────────────────
    # `reading_progress.last_chapter` only tracks the cursor (the most-
    # recently-opened chapter). The set below tracks every individual
    # chapter the user has opened in the Reader, so the Library card and
    # Detail chapter rows can show a per-chapter read indicator.

    def mark_chapter_read(self, manga_title: str, chapter):
        """Add `chapter` to the per-manga read set (idempotent)."""
        if chapter is None or str(chapter).strip() == "":
            return
        self._ensure_manga_entry(manga_title)
        entry = self._data["manga"][manga_title]
        read_list = entry.setdefault("read_chapters", [])
        ch = str(chapter)
        if ch not in read_list:
            read_list.append(ch)
            self._mark_dirty()

    def unmark_chapter_read(self, manga_title: str, chapter):
        entry = self._data.get("manga", {}).get(manga_title)
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
        return list(self.get_manga_state(manga_title).get("read_chapters", []) or [])

    def get_read_count(self, manga_title: str) -> int:
        return len(self.get_manga_state(manga_title).get("read_chapters", []) or [])

    # ========================================================================
    # New Chapter Badges
    # ========================================================================

    def set_new_chapters(self, manga_title: str, count: int):
        """Set the number of new chapters available for a manga."""
        self._ensure_manga_entry(manga_title)
        self._data["manga"][manga_title]["new_chapters_available"] = count
        self._mark_dirty()

    def get_new_chapters(self, manga_title: str) -> int:
        """Get the number of new chapters available."""
        return self.get_manga_state(manga_title).get("new_chapters_available", 0)

    def clear_new_chapters(self, manga_title: str):
        """Clear the new chapters badge (e.g. after downloading)."""
        state = self.get_manga_state(manga_title)
        if state and state.get("new_chapters_available", 0) > 0:
            self._data["manga"][manga_title]["new_chapters_available"] = 0
            self._mark_dirty()

    def decrement_new_chapters(self, manga_title: str):
        """Decrement the new chapters badge by 1 (used by manual single downloads)."""
        state = self.get_manga_state(manga_title)
        current = state.get("new_chapters_available", 0) if state else 0
        if current > 0:
            self._data["manga"][manga_title]["new_chapters_available"] = current - 1
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
        self._ensure_manga_entry(manga_title)
        self._data["manga"][manga_title]["available_chapters"] = chapters
        self._mark_dirty()

    def get_available_chapters(self, manga_title: str) -> List[Dict[str, Any]]:
        """Get the cached chapter list for a manga (empty list if never checked)."""
        return self.get_manga_state(manga_title).get("available_chapters", [])

    # ========================================================================
    # External Chapters (already read outside the app)
    # ========================================================================

    def mark_external_chapter(self, manga_title: str, chapter: str):
        """Record a chapter that was read outside MeManga.

        Stored separately from `downloaded` so the app never lies about what's
        on disk; the Detail page renders these as "Read elsewhere" rows.
        """
        self._ensure_manga_entry(manga_title)
        entry = self._data["manga"][manga_title]
        if "external_chapters" not in entry:
            entry["external_chapters"] = []
        ch_str = str(chapter)
        if ch_str not in entry["external_chapters"]:
            entry["external_chapters"].append(ch_str)

            def _sort_key(x):
                try:
                    return float(x)
                except (ValueError, TypeError):
                    return 0.0

            entry["external_chapters"].sort(key=_sort_key)
            self._mark_dirty()

    def get_external_chapters(self, manga_title: str) -> List[str]:
        """Get the chapters the user marked as already read elsewhere."""
        return self.get_manga_state(manga_title).get("external_chapters", [])

    def is_external_chapter(self, manga_title: str, chapter: str) -> bool:
        """Whether a chapter was previously marked as read-elsewhere."""
        return str(chapter) in self.get_external_chapters(manga_title)

    # ========================================================================
    # Notifications
    # ========================================================================

    def add_notification(self, ntype: str, message: str):
        """Add a notification to the log."""
        if "notifications" not in self._data:
            self._data["notifications"] = []
        self._data["notifications"].append({
            "type": ntype,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        })
        self._data["notifications"] = self._data["notifications"][-100:]
        self._mark_dirty()

    def get_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent notifications."""
        return list(reversed(self._data.get("notifications", [])[-limit:]))

    def get_unread_count(self) -> int:
        """Count unread notifications."""
        return sum(1 for n in self._data.get("notifications", []) if not n.get("read"))

    def mark_notifications_read(self):
        """Mark all notifications as read."""
        for n in self._data.get("notifications", []):
            n["read"] = True
        self._mark_dirty()

    def clear_notifications(self):
        """Wipe all notifications. Used by the GUI's 'Clear all' button."""
        self._data["notifications"] = []
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
        all_notifs = list(reversed(self._data.get("notifications", [])[-limit:]))
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
        history = self._data.get("search_history", []) or []
        # Dedupe by case-insensitive match, then prepend.
        history = [h for h in history if h.lower() != q.lower()]
        history.insert(0, q)
        self._data["search_history"] = history[:limit]
        self._mark_dirty()

    def get_recent_searches(self, limit: int = 8) -> List[str]:
        return list(self._data.get("search_history", []) or [])[:limit]

    def clear_search_history(self):
        self._data["search_history"] = []
        self._mark_dirty()

    # ========================================================================
    # Download History
    # ========================================================================

    def add_download_history(self, title: str, chapter: str, fmt: str,
                             path: str = "", size_mb: float = 0, kindle_sent: bool = False):
        """Log a completed download."""
        if "download_history" not in self._data:
            self._data["download_history"] = []
        self._data["download_history"].append({
            "title": title,
            "chapter": chapter,
            "format": fmt,
            "path": path,
            "size_mb": round(size_mb, 2),
            "kindle_sent": kindle_sent,
            "timestamp": datetime.now().isoformat(),
        })
        self._data["download_history"] = self._data["download_history"][-200:]
        self._mark_dirty()

    def get_download_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent download history."""
        return list(reversed(self._data.get("download_history", [])[-limit:]))

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
        if "source_health" not in self._data:
            self._data["source_health"] = {}
        now = datetime.now().isoformat()
        health = self._data["source_health"].get(domain, {"error_count": 0})
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
        self._data["source_health"][domain] = health
        self._mark_dirty()

    def get_source_health(self, domain: str) -> Dict[str, Any]:
        """Get health info for a source."""
        return self._data.get("source_health", {}).get(domain, {})

    def get_all_source_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health info for all sources."""
        return self._data.get("source_health", {})

    def reset_manga_progress(self, manga_title: str, from_chapter: float = 0):
        """Reset a manga's download progress to re-download from a specific chapter.
        If from_chapter is 0, clears everything for a full re-download.
        If from_chapter is N, keeps chapters < N downloaded and re-downloads N onwards.
        """
        self._ensure_manga_entry(manga_title)
        entry = self._data["manga"][manga_title]
        if from_chapter == 0:
            entry["last_chapter"] = None
            entry["downloaded"] = []
        else:
            # Keep only chapters before from_chapter, remove the rest
            entry["downloaded"] = [
                ch for ch in entry.get("downloaded", [])
                if float(ch) < from_chapter
            ]
            entry["last_chapter"] = None
        entry["last_updated"] = datetime.now().isoformat()
        self.save()

    # ========================================================================
    # Cleanup
    # ========================================================================
    
    def remove_manga(self, manga_title: str) -> bool:
        """Remove a manga from state."""
        if manga_title in self._data.get("manga", {}):
            del self._data["manga"][manga_title]
            self.save()
            return True
        return False
    
    def clear_all(self):
        """Clear all state (fresh start)."""
        self._data = self._default_state()
        self.save()
