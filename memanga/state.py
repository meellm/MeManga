"""
State management for MeManga - tracks downloaded chapters and check history
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any


class State:
    """Manages state file (tracking what's been downloaded)."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".config" / "memanga"
        
        self.state_path = self.config_dir / "state.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
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
        }
    
    def save(self):
        """Save state to file."""
        with open(self.state_path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)
    
    def get(self, key: str, default=None):
        """Get a state value."""
        return self._data.get(key, default)
    
    def set(self, key: str, value):
        """Set a state value."""
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
            self._data["manga"][manga_title]["downloaded"].sort(key=lambda x: float(x) if x.replace('.', '').isdigit() else 0)
        
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
