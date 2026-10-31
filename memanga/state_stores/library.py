"""Library and download state: what is saved on disk for each manga."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from ..backup import merge_backup_state
from ..chapters import chapter_sort_key, chapter_value
from ._base import StateDomain, snapshot


class LibraryStore(StateDomain):
    """Manga entries, downloaded and read-elsewhere chapters, saved
    chapter groups, and whole-entry operations (reset, rename, remove,
    backup import)."""

    __slots__ = ()

    def get_entry(self, manga_title: str) -> Dict[str, Any]:
        """Get full state for a manga (a snapshot, not the live entry)."""
        with self._backend._locked() as data:
            entry = data.get("manga", {}).get(manga_title, {})
            return {k: snapshot(v) for k, v in entry.items()}

    def get_last_chapter(self, manga_title: str) -> Optional[str]:
        """Get the last downloaded chapter number for a manga."""
        return self._backend._entry_value(manga_title, "last_chapter")

    def set_last_chapter(self, manga_title: str, chapter: str) -> None:
        """Set the last downloaded chapter for a manga.

        Marks dirty rather than syncing — the app's 5s flush timer + the
        closeEvent flush cover durability without thrashing disk on
        every per-chapter update.
        """
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            data["manga"][manga_title]["last_chapter"] = chapter
            data["manga"][manga_title]["last_updated"] = datetime.now().isoformat()
            self._backend._mark_dirty()

    def get_downloaded(self, manga_title: str) -> List[str]:
        """Get list of all downloaded chapter numbers for a manga."""
        return self._backend._entry_value(manga_title, "downloaded", [])

    def add_downloaded(self, manga_title: str, chapter: str) -> None:
        """Mark a chapter as downloaded."""
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]

            if "downloaded" not in entry:
                entry["downloaded"] = []

            chapter_str = str(chapter)
            if chapter_str not in entry["downloaded"]:
                entry["downloaded"].append(chapter_str)
                entry["downloaded"].sort(key=chapter_sort_key)

            entry["last_chapter"] = chapter_str
            entry["last_updated"] = datetime.now().isoformat()
            self._backend._mark_dirty()

    def is_downloaded(self, manga_title: str, chapter: str) -> bool:
        """Check if a chapter has been downloaded."""
        return str(chapter) in self.get_downloaded(manga_title)

    def remove_downloaded(self, manga_title: str, chapter: str) -> bool:
        """Drop a single chapter from the downloaded list (issue #104).

        Deliberately narrow: it touches only ``downloaded`` and leaves
        ``read_chapters`` alone, so removing a chapter's local file after
        it is read returns the Detail row to the Download state without
        losing read progress. Returns True if the chapter was present.
        No-op for unknown manga or chapters not marked downloaded.
        """
        with self._backend._locked() as data:
            manga_state = data.get("manga", {}).get(manga_title)
            if not manga_state:
                return False
            downloaded = manga_state.get("downloaded", [])
            chapter_str = str(chapter)
            if chapter_str not in downloaded:
                return False
            downloaded.remove(chapter_str)
            manga_state.get("saved_chapter_groups", {}).pop(chapter_str, None)
            self._backend._mark_dirty()
            return True

    def set_chapter_groups(self, manga_title: str, chapter: str, source: str,
                           group_ids: List[str], group_names: List[str]) -> None:
        """Record the scanlation group(s) of a saved chapter (issue #400).

        Kept apart from ``available_chapters`` so a later check, which may
        drop a removed group's upload from the feed, can't erase who the
        saved file came from.
        """
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            entry.setdefault("saved_chapter_groups", {})[str(chapter)] = {
                "source": source,
                "group_ids": list(group_ids or []),
                "group_names": list(group_names or []),
            }
            self._backend._mark_dirty()

    def get_chapter_groups(self, manga_title: str, chapter: str) -> Dict[str, Any]:
        """Saved chapter's group record, or an empty dict if none was kept."""
        groups = self._backend._entry_value(manga_title, "saved_chapter_groups", {}) or {}
        return groups.get(str(chapter), {})

    # ── External chapters (already read outside the app) ───────────────

    def mark_external(self, manga_title: str, chapter: str) -> None:
        """Record a chapter that was read outside MeManga.

        Stored separately from `downloaded` so the app never lies about what's
        on disk; the Detail page renders these as "Read elsewhere" rows.
        """
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if "external_chapters" not in entry:
                entry["external_chapters"] = []
            ch_str = str(chapter)
            if ch_str not in entry["external_chapters"]:
                entry["external_chapters"].append(ch_str)
                entry["external_chapters"].sort(key=chapter_sort_key)
                self._backend._mark_dirty()

    def get_external(self, manga_title: str) -> List[str]:
        """Get the chapters the user marked as already read elsewhere."""
        return self._backend._entry_value(manga_title, "external_chapters", [])

    def is_external(self, manga_title: str, chapter: str) -> bool:
        """Whether a chapter was previously marked as read-elsewhere."""
        return str(chapter) in self.get_external(manga_title)

    # ── Whole-entry operations ─────────────────────────────────────────

    def reset_progress(self, manga_title: str, from_chapter: float = 0) -> None:
        """Reset a manga's download progress to re-download from a specific chapter.
        If from_chapter is 0, clears everything for a full re-download.
        If from_chapter is N, keeps chapters < N downloaded and re-downloads N onwards.
        """
        with self._backend._locked() as data:
            self._backend._ensure_manga_entry(manga_title)
            entry = data["manga"][manga_title]
            if from_chapter == 0:
                entry["last_chapter"] = None
                entry["downloaded"] = []
                entry["partial_chapters"] = {}
            else:
                # Keep only chapters before from_chapter, remove the rest.
                # Labelled chapters (e.g. "Chapter 3" or "3 Part 1") compare
                # by their embedded chapter number. Labels with no number are preserved
                # because they cannot be ordered safely against the threshold.
                def _keep_downloaded(ch):
                    num = chapter_value(ch)
                    return num is None or num < from_chapter

                entry["downloaded"] = [
                    ch for ch in entry.get("downloaded", [])
                    if _keep_downloaded(ch)
                ]
                entry["partial_chapters"] = {
                    ch: info
                    for ch, info in entry.get("partial_chapters", {}).items()
                    if _keep_downloaded(ch)
                }
                entry["last_chapter"] = None
            entry["last_updated"] = datetime.now().isoformat()
            self._backend.save()

    def rename(self, old_title: str, new_title: str) -> bool:
        """Move a manga's state entry to a new title (edit/rename flows).

        Issue #110: replaces the GUI's direct ``_data`` pokes so renames go
        through the lock like every other mutation.

        Issue #392: its download-history rows move with it, so deleting
        its history later finds them. A manga added under the old title
        afterwards logs new rows, which stay its own. The rows move even
        without a state entry (history kept from an earlier removal);
        returns whether anything moved.
        """
        with self._backend._locked() as data:
            manga = data.get("manga", {})
            moved = old_title in manga
            if moved:
                manga[new_title] = manga.pop(old_title)
            for entry in data.get("download_history", []):
                if entry.get("title") == old_title:
                    entry["title"] = new_title
                    moved = True
            if moved:
                self._backend.save()
            return moved

    def has_history(self, manga_title: str) -> bool:
        """Whether anything is still saved under ``manga_title``: a state
        entry or download-history rows (issue #392).

        Renaming a manga onto such a title would mix its history with
        records that can't be told apart from it, so rename flows refuse.
        """
        with self._backend._locked() as data:
            return (manga_title in data.get("manga", {})
                    or any(e.get("title") == manga_title
                           for e in data.get("download_history", [])))

    def remove(self, manga_title: str) -> bool:
        """Remove a manga from state."""
        with self._backend._locked() as data:
            if manga_title in data.get("manga", {}):
                del data["manga"][manga_title]
                self._backend.save()
                return True
            return False

    def merge_missing(
        self,
        imported_state: Dict[str, Any],
        *,
        merge_existing_downloaded: bool = False,
        title_aliases: Optional[Mapping[str, str]] = None,
    ) -> None:
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
        with self._backend._locked() as data:
            manga = data.setdefault("manga", {})
            if merge_existing_downloaded:
                data["manga"] = snapshot(
                    merge_backup_state(
                        manga,
                        imported_state,
                        title_aliases=title_aliases,
                    )
                )
            else:
                for title, state_data in imported_state.items():
                    if not manga.get(title):
                        manga[title] = snapshot(state_data)
            self._backend.save()
