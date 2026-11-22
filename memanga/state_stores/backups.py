"""Backup-source and suspicious-batch holds."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ._base import StateDomain, snapshot


class BackupStore(StateDomain):
    """Chapters waiting on the primary source after a backup sighting,
    and chapter batches held back as suspicious."""

    __slots__ = ()

    def get_pending(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """Get pending backup info for a chapter (if waiting for primary to catch up)."""
        pending = self._backend._entry_value(manga_title, "pending_backup", {})
        return pending.get(str(chapter))

    def set_pending(self, manga_title: str, chapter: str, backup_source: str,
                    backup_url: str) -> None:
        """Mark a chapter as seen on backup source, start the waiting period."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
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
                self._backend.save()

    def clear_pending(self, manga_title: str, chapter: str) -> None:
        """Clear pending backup for a chapter (downloaded from primary or backup)."""
        with self._backend._locked() as data:
            pending = data.get("manga", {}).get(manga_title, {}).get("pending_backup", {})

            chapter_str = str(chapter)
            if chapter_str in pending:
                del pending[chapter_str]
                self._backend.save()

    def clear_all_pending(self, manga_title: str) -> None:
        """Clear all pending backups for a manga."""
        with self._backend._locked() as data:
            if manga_title in data.get("manga", {}):
                data["manga"][manga_title]["pending_backup"] = {}
                self._backend.save()

    def get_all_pending(self, manga_title: str) -> Dict[str, Dict[str, Any]]:
        """Get all pending backup chapters for a manga."""
        return self._backend._entry_value(manga_title, "pending_backup", {})

    # ── Suspicious batches ─────────────────────────────────────────────

    def set_suspicious_batch(self, manga_title: str, info: Dict[str, Any]) -> None:
        """Record a suspicious chapter batch that was held back from
        download/delivery. ``info`` should describe the batch (chapters,
        score, reasons, backup verification status, detected_at)."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["suspicious_batch"] = snapshot(info)
            self._backend.save()

    def get_suspicious_batch(self, manga_title: str) -> Optional[Dict[str, Any]]:
        """Get the held-back suspicious batch for a manga, if any."""
        return self._backend._entry_value(manga_title, "suspicious_batch")

    def clear_suspicious_batch(self, manga_title: str) -> None:
        """Clear the suspicious batch record (accepted, confirmed, or stale)."""
        with self._backend._locked() as data:
            manga_state = data.get("manga", {}).get(manga_title, {})
            if "suspicious_batch" in manga_state:
                del manga_state["suspicious_batch"]
                self._backend.save()
