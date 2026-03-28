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
        """Set the last downloaded chapter for a manga."""
        self._ensure_manga_entry(manga_title)
        self._data["manga"][manga_title]["last_chapter"] = chapter
        self._data["manga"][manga_title]["last_updated"] = datetime.now().isoformat()
        self.save()
    
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
        self.save()
    
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

    def update_source_health(self, domain: str, success: bool, error_msg: str = ""):
        """Update health status for a source domain."""
        if "source_health" not in self._data:
            self._data["source_health"] = {}
        now = datetime.now().isoformat()
        health = self._data["source_health"].get(domain, {"error_count": 0})
        if success:
            health["last_success"] = now
            health["error_count"] = 0
            health["status"] = "ok"
        else:
            health["last_error"] = now
            health["last_error_msg"] = error_msg[:100]
            health["error_count"] = health.get("error_count", 0) + 1
            health["status"] = "warning" if health["error_count"] < 3 else "error"
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
