"""Failed, accepted-partial and undelivered chapter records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ._base import StateDomain, snapshot


def delivery_timestamp() -> str:
    """Now as an ISO 8601 UTC time with a fixed precision, e.g.
    ``2026-10-22T08:00:00.000000+00:00``.

    Kindle delivery records (issue #360) are ordered by these times when
    backups merge, so they must compare across time zones, DST changes and
    machines; naive local times cannot.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class FailureStore(StateDomain):
    """Chapters whose download failed, partial chapters the user
    accepted but that stay retryable, and saved chapters whose Kindle
    delivery failed."""

    __slots__ = ()

    def add_failed(
        self,
        manga_title: str,
        chapter: str,
        source: str,
        error: str,
        failed_pages: Optional[List[int]] = None,
    ) -> None:
        """Record a chapter download failure."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            chapter_str = str(chapter)
            entry = data["manga"][manga_title]

            if "failed_chapters" not in entry:
                entry["failed_chapters"] = {}

            existing = entry["failed_chapters"].get(chapter_str, {})
            entry["failed_chapters"][chapter_str] = {
                "failed_at": datetime.now().isoformat(),
                "source": source,
                "error": error[:300],
                "failed_pages": snapshot(failed_pages or []),
                "attempts": existing.get("attempts", 0) + 1,
            }
            self._backend.save()

    def get_failed(self, manga_title: str) -> Dict[str, Any]:
        """Get all failed chapter records for a manga."""
        return self._backend._entry_value(manga_title, "failed_chapters", {})

    def get_all_failed(self) -> Dict[str, Dict[str, Any]]:
        """Get failed chapters for all manga that have failures."""
        with self._backend._locked() as data:
            result = {}
            for title, manga_state in data.get("manga", {}).items():
                failed = manga_state.get("failed_chapters", {})
                if failed:
                    result[title] = snapshot(failed)
            return result

    def clear_failed(self, manga_title: str, chapter: str) -> None:
        """Remove a failed chapter record after successful re-download."""
        with self._backend._locked() as data:
            chapter_str = str(chapter)
            failed = data.get("manga", {}).get(manga_title, {}).get("failed_chapters", {})
            if chapter_str in failed:
                del failed[chapter_str]
                self._backend.save()

    # ── Accepted partial chapters ──────────────────────────────────────

    def add_partial(
        self,
        manga_title: str,
        chapter: str,
        source: str = "",
        failed_pages: Optional[List[int]] = None,
        total_pages: int = 0,
        path: str = "",
        from_backup: bool = False,
    ) -> None:
        """Record an accepted partial chapter so it remains retryable."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            chapter_str = str(chapter)
            entry = data["manga"][manga_title]
            entry.setdefault("partial_chapters", {})[chapter_str] = {
                "accepted_at": datetime.now().isoformat(),
                "source": source,
                "failed_pages": snapshot(failed_pages or []),
                "total_pages": int(total_pages or 0),
                "path": path,
                "from_backup": bool(from_backup),
            }
            self._backend.save()

    def get_partials(self, manga_title: str) -> Dict[str, Any]:
        """Get accepted partial chapter records for a manga."""
        return self._backend._entry_value(manga_title, "partial_chapters", {})

    def get_partial(self, manga_title: str, chapter: str) -> Optional[Dict[str, Any]]:
        """Get one accepted partial chapter record."""
        partials = self.get_partials(manga_title)
        return partials.get(str(chapter))

    def get_all_partials(self) -> Dict[str, Dict[str, Any]]:
        """Get accepted partial chapters for all manga."""
        with self._backend._locked() as data:
            return {
                title: snapshot(partials)
                for title, manga_state in data.get("manga", {}).items()
                if (partials := manga_state.get("partial_chapters", {}))
            }

    def clear_partial(self, manga_title: str, chapter: str) -> None:
        """Remove an accepted partial record after a complete re-download."""
        with self._backend._locked() as data:
            chapter_str = str(chapter)
            partials = data.get("manga", {}).get(manga_title, {}).get("partial_chapters", {})
            if chapter_str in partials:
                del partials[chapter_str]
                self._backend.save()

    # ── Chapters saved but not delivered to Kindle (issue #360) ────────

    def add_undelivered(
        self,
        manga_title: str,
        chapter: str,
        path: str,
        error: str,
        parts: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a saved chapter whose Kindle delivery failed, so it can
        be sent again. The chapter stays downloaded; ``path`` is the file
        that was kept for the retry.

        ``parts`` is the delivery progress of a split PDF (issue #364):
        which parts the mail server already accepted, so a retry does not
        send them again. Without it, the progress already on record is
        kept (a failure before any part was tried changes nothing)."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            chapter_str = str(chapter)
            entry = data["manga"][manga_title]
            undelivered = entry.setdefault("undelivered_chapters", {})
            existing = undelivered.get(chapter_str, {})
            record = {
                "failed_at": delivery_timestamp(),
                "path": path,
                "error": error[:300],
                "attempts": existing.get("attempts", 0) + 1,
            }
            if parts is None:
                parts = existing.get("parts")
            if isinstance(parts, dict):
                record["parts"] = snapshot(parts)
            undelivered[chapter_str] = record
            # A new failure supersedes an earlier resolution.
            resolved = entry.get("resolved_deliveries")
            if isinstance(resolved, dict):
                resolved.pop(chapter_str, None)
            self._backend.save()

    def get_undelivered(self, manga_title: str) -> Dict[str, Any]:
        """Undelivered chapter records for a manga."""
        records = self._backend._entry_value(manga_title, "undelivered_chapters", {})
        return records if isinstance(records, dict) else {}

    def get_all_undelivered(self) -> Dict[str, Dict[str, Any]]:
        """Undelivered chapters for all manga that have any."""
        with self._backend._locked() as data:
            return {
                title: snapshot(records)
                for title, manga_state in data.get("manga", {}).items()
                if isinstance(records := manga_state.get("undelivered_chapters"), dict)
                and records
            }

    def clear_undelivered(self, manga_title: str, chapter: str,
                          reason: str = "cleared") -> None:
        """Remove an undelivered record once the chapter reached the Kindle
        (``reason="sent"``) or the user dismissed it.

        The resolution is kept under ``resolved_deliveries`` so importing
        an older backup cannot bring the record back and send the chapter
        twice (see :func:`memanga.backup.merge_manga_state`).
        """
        with self._backend._locked() as data:
            chapter_str = str(chapter)
            entry = data.get("manga", {}).get(manga_title, {})
            records = entry.get("undelivered_chapters", {})
            if chapter_str in records:
                del records[chapter_str]
                resolved = entry.get("resolved_deliveries")
                if not isinstance(resolved, dict):
                    resolved = entry["resolved_deliveries"] = {}
                resolved[chapter_str] = {
                    "resolved_at": delivery_timestamp(),
                    "reason": reason,
                }
                self._backend.save()
