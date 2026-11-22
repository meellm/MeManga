"""Reader state: progress cursor, in-chapter positions and the read set."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ._base import StateDomain, snapshot


class ReadingStore(StateDomain):
    """What the user has read and where the Reader left off."""

    __slots__ = ()

    def set_progress(self, manga_title: str, chapter: str) -> None:
        """Update the last-read chapter for a manga."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if "reading_progress" not in entry:
                entry["reading_progress"] = {}
            entry["reading_progress"]["last_chapter"] = str(chapter)
            entry["reading_progress"]["last_read"] = datetime.now().isoformat()
            self._backend._mark_dirty()

    def get_progress(self, manga_title: str) -> Dict[str, Any]:
        """Get reading progress for a manga."""
        return self._backend._entry_value(manga_title, "reading_progress", {})

    def get_continue_reading(self) -> Optional[Dict[str, Any]]:
        """Get the most recently read manga for 'Continue Reading' widget."""
        with self._backend._locked() as data:
            best = None
            best_time = None
            for title, entry in data.get("manga", {}).items():
                progress = entry.get("reading_progress", {})
                last_read = progress.get("last_read")
                if last_read and progress.get("last_chapter"):
                    if best_time is None or last_read > best_time:
                        best_time = last_read
                        best = {"title": title, **progress}
            return snapshot(best)

    # ── Reader resume position (issue #106) ────────────────────────────
    # Separate from `reading_progress.last_chapter` (the cursor) and
    # `read_chapters` (the read set): this stores *where inside a chapter*
    # the reader left off, so reopening a chapter can restore the exact
    # page (paged mode) or scroll offset (webtoon/strip mode).

    def set_position(self, manga_title: str, chapter, mode: str,
                     page_index: Optional[int] = None,
                     scroll_ratio: Optional[float] = None) -> None:
        """Save the in-chapter resume position for a manga/chapter."""
        if chapter is None or str(chapter).strip() == "":
            return
        # Issue #224: take the shared reentrant lock (#110) so creating the
        # entry/positions dicts can't race a worker or the periodic
        # flush/save; ``_ensure_manga_entry`` also requires it held.
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
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
            self._backend._mark_dirty()

    def get_position(self, manga_title: str, chapter) -> Optional[Dict[str, Any]]:
        """Get the saved resume position, or None if never saved."""
        positions = self._backend._entry_value(manga_title, "reader_positions", {})
        return positions.get(str(chapter))

    def clear_position(self, manga_title: str, chapter) -> None:
        """Drop the saved resume position (e.g. chapter finished)."""
        # Issue #224: check-then-delete under the shared lock so a
        # concurrent flush/save never serializes the dict mid-removal.
        with self._backend._locked() as data:
            positions = data.get("manga", {}).get(manga_title, {}).get("reader_positions", {})
            ch = str(chapter)
            if ch in positions:
                del positions[ch]
                self._backend._mark_dirty()

    # ── Per-chapter read tracking (issue #18) ──────────────────────────
    # `reading_progress.last_chapter` only tracks the cursor (the most-
    # recently-opened chapter). The set below tracks every individual
    # chapter the user has opened in the Reader, so the Library card and
    # Detail chapter rows can show a per-chapter read indicator.

    def mark_read(self, manga_title: str, chapter) -> None:
        """Add `chapter` to the per-manga read set (idempotent)."""
        if chapter is None or str(chapter).strip() == "":
            return
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            read_list = entry.setdefault("read_chapters", [])
            ch = str(chapter)
            if ch not in read_list:
                read_list.append(ch)
                self._backend._mark_dirty()

    def unmark_read(self, manga_title: str, chapter) -> None:
        """Remove `chapter` from the per-manga read set (no-op if absent)."""
        with self._backend._locked() as data:
            entry = data.get("manga", {}).get(manga_title)
            if not entry:
                return
            read_list = entry.get("read_chapters", [])
            ch = str(chapter)
            if ch in read_list:
                read_list.remove(ch)
                self._backend._mark_dirty()

    def is_read(self, manga_title: str, chapter) -> bool:
        """Whether `chapter` is in the per-manga read set."""
        return str(chapter) in self.get_read(manga_title)

    def get_read(self, manga_title: str) -> List[str]:
        """Chapters in the per-manga read set (a copy)."""
        return self._backend._entry_value(manga_title, "read_chapters", []) or []

    def get_read_count(self, manga_title: str) -> int:
        """Number of chapters read, without snapshotting the read list.

        The Library page calls this per manga on every refresh (grid
        cards + the header's read total), so it counts under the lock
        instead of paying get_read()'s deep copy each time.
        """
        with self._backend._locked() as data:
            return len(
                data.get("manga", {}).get(manga_title, {}).get("read_chapters", []) or []
            )
