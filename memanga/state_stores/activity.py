"""Activity history: update checks, completed downloads and totals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ._base import StateDomain, snapshot


class ActivityStore(StateDomain):
    """Check history, download history and overall statistics."""

    __slots__ = ()

    MAX_CHECKS = 50
    MAX_DOWNLOADS = 200

    def record_check(self, new_chapters: int = 0, downloaded: int = 0) -> None:
        """Update the last check timestamp and log the check to history."""
        with self._backend._locked() as data:
            now = datetime.now().isoformat()
            data["last_check"] = now

            if "check_history" not in data:
                data["check_history"] = []

            data["check_history"].append({
                "timestamp": now,
                "new_chapters": new_chapters,
                "downloaded": downloaded,
            })

            data["check_history"] = data["check_history"][-self.MAX_CHECKS:]

            self._backend.save()

    def get_check_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent check history."""
        with self._backend._locked() as data:
            return snapshot(data.get("check_history", [])[-limit:])

    def add_download(self, title: str, chapter: str, fmt: str,
                     path: str = "", size_mb: float = 0, kindle_sent: bool = False,
                     *, source: Optional[str] = None, from_backup: bool = False,
                     partial: bool = False,
                     deleted_after_send: bool = False) -> None:
        """Log a completed download.

        ``source`` is where the chapter came from; ``from_backup`` and
        ``partial`` mark a backup-source save and an accepted partial.
        ``deleted_after_send`` marks a sent chapter whose local copy was
        deleted afterwards (#338); ``path`` no longer exists then.
        """
        with self._backend._locked() as data:
            if "download_history" not in data:
                data["download_history"] = []
            data["download_history"].append({
                "title": title,
                "chapter": chapter,
                "format": fmt,
                "path": path,
                "size_mb": round(size_mb, 2),
                "kindle_sent": kindle_sent,
                "source": source,
                "from_backup": from_backup,
                "partial": partial,
                "deleted_after_send": deleted_after_send,
                "timestamp": datetime.now().isoformat(),
            })
            data["download_history"] = data["download_history"][-self.MAX_DOWNLOADS:]
            self._backend._mark_dirty()

    def mark_download_sent(self, title: str, chapter: str, path: str = "",
                           *, deleted_after_send: bool = False) -> bool:
        """Mark a logged download as sent after a later send succeeded.

        Updates the newest entry for ``title`` and ``chapter`` (and
        ``path``, when given) that is not marked sent yet; other entries
        are left as they are (#338). Returns whether an entry was updated.
        """
        chapter = str(chapter)
        with self._backend._locked() as data:
            for entry in reversed(data.get("download_history", [])):
                if (entry.get("title") != title
                        or str(entry.get("chapter")) != chapter
                        or entry.get("kindle_sent")
                        or (path and entry.get("path") != path)):
                    continue
                entry["kindle_sent"] = True
                entry["deleted_after_send"] = deleted_after_send
                self._backend._mark_dirty()
                return True
        return False

    def get_download_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent download history, newest first."""
        with self._backend._locked() as data:
            return snapshot(
                list(reversed(data.get("download_history", [])[-limit:])))

    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        with self._backend._locked() as data:
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
