"""Catalogue state: what the sources offer for each manga."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._base import StateDomain, snapshot


class CatalogueStore(StateDomain):
    """Available-chapter cache, trusted catalogue baseline and the
    new-chapter badge count."""

    __slots__ = ()

    def set_available(self, manga_title: str, chapters: List[Dict[str, Any]]) -> None:
        """Cache the full list of chapters from the last check (for both modes).

        Each entry should contain: number, title, source, source_url, is_backup.
        Used by the Detail page to show every chapter as 'Read' (downloaded) or
        'Download' (available) without re-scraping.
        """
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            # Keep the group of chapters saved before their record existed:
            # the new list may no longer include that group's upload.
            downloaded = set(entry.get("downloaded", []))
            for old in entry.get("available_chapters", []) or []:
                num = str(old.get("number", ""))
                if (num in downloaded
                        and num not in entry.get("saved_chapter_groups", {})
                        and (old.get("group_ids") or old.get("group_names"))):
                    entry.setdefault("saved_chapter_groups", {})[num] = {
                        "source": old.get("source", ""),
                        "group_ids": list(old.get("group_ids", [])),
                        "group_names": list(old.get("group_names", [])),
                    }
            entry["available_chapters"] = snapshot(list(chapters))
            self._backend._mark_dirty()

    def get_available(self, manga_title: str) -> List[Dict[str, Any]]:
        """Get the cached chapter list for a manga (empty list if never checked)."""
        return self._backend._entry_value(manga_title, "available_chapters", [])

    def get_available_count(self, manga_title: str) -> int:
        """Number of cached available chapters, without snapshotting them.

        Callers that only need the total (Library cards' "Read X/N"
        line) would otherwise deep-copy the whole cached list - per
        card, per refresh - just to call len() on it.
        """
        with self._backend._locked() as data:
            return len(
                data.get("manga", {}).get(manga_title, {}).get("available_chapters", []) or []
            )

    def get_baseline(self, manga_title: str) -> Optional[float]:
        """Highest chapter number the source has legitimately exposed so far.

        This "last seen available chapter" high-water mark lets the
        suspicious-batch guard tell an existing-but-undownloaded backlog
        apart from a genuine source jump (#102). Returns ``None`` when no
        trusted snapshot has been recorded yet.
        """
        value = self._backend._entry_value(manga_title, "catalogue_baseline")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def set_baseline(self, manga_title: str, highest: float) -> None:
        """Record the trusted catalogue high-water mark for a manga (#102).

        Only ever called with a value the source has actually shown and that
        the guard did not hold back, so it never advances past an unverified
        suspicious jump.
        """
        # Issue #224: update checks call this from background workers, so
        # it needs the same shared lock as every other mutator (#110).
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            try:
                data["manga"][manga_title]["catalogue_baseline"] = float(highest)
            except (TypeError, ValueError):
                return
            self._backend._mark_dirty()

    # ── New-chapter badges ─────────────────────────────────────────────

    def set_new_count(self, manga_title: str, count: int) -> None:
        """Set the number of new chapters available for a manga."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["new_chapters_available"] = count
            self._backend._mark_dirty()

    def get_new_count(self, manga_title: str) -> int:
        """Get the number of new chapters available."""
        return self._backend._entry_value(manga_title, "new_chapters_available", 0)

    def clear_new_count(self, manga_title: str) -> None:
        """Clear the new chapters badge (e.g. after downloading)."""
        with self._backend._locked() as data:
            entry = data.get("manga", {}).get(manga_title, {})
            if entry.get("new_chapters_available", 0) > 0:
                entry["new_chapters_available"] = 0
                self._backend._mark_dirty()

    def decrement_new_count(self, manga_title: str) -> None:
        """Decrement the new chapters badge by 1 (used by manual single downloads)."""
        with self._backend._locked() as data:
            entry = data.get("manga", {}).get(manga_title, {})
            current = entry.get("new_chapters_available", 0)
            if current > 0:
                entry["new_chapters_available"] = current - 1
                self._backend._mark_dirty()
