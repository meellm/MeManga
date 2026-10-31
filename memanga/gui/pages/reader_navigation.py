"""
Reader chapter navigation: Prev/Next order across downloaded chapters
and the quiet next-chapter prefetch (issue #107) for ReaderPage.
"""

from typing import List, Optional

from ...chapters import chapter_value


def _chapter_sort_key(number) -> Optional[float]:
    """Numeric sort key for a chapter number, or None when it can't be
    parsed. Used by the reader prefetch (issue #107) to find the
    immediate next chapter without assuming the cache is pre-sorted.
    Uses Chapter.numeric's rules so labels like "Chapter 2" or "2 Part 1"
    resolve too, but yields None instead of 0.0 when nothing numeric is
    found -- an unparseable chapter must skip prefetch, not sort as
    chapter zero."""
    return chapter_value(number)


_PREFETCH_SKIP = object()


class ReaderNavigationMixin:
    """Prev/Next chapter navigation and next-chapter prefetch.

    ReaderPage initialises the state used here (``_manga``, ``_chapter``,
    ``_navigation_chapters``, the Next control handles and the prefetch
    fallback keys), subscribes the event handlers and provides
    ``_load_chapter`` and ``save_reading_position``."""

    def _navigate_chapter(self, chapter):
        # Issue #106: keep the outgoing chapter's resume point before the
        # cursor moves on — Prev/Next never goes through on_hide.
        self.save_reading_position()
        self._chapter = chapter
        if self._manga:
            title = self._manga.get("title", "")
            if title:
                self.app.app_state.set_reading_progress(title, str(chapter))
        self._load_chapter()
        self.setFocus()

    def _go_next_chapter(self):
        if not self._manga:
            return
        title = self._manga.get("title", "")
        next_ch = self._navigation_neighbor(+1, title)
        if next_ch is not None:
            self._navigate_chapter(next_ch)

    def _go_prev_chapter(self):
        if not self._manga:
            return
        title = self._manga.get("title", "")
        prev_ch = self._navigation_neighbor(-1, title)
        if prev_ch is not None:
            self._navigate_chapter(prev_ch)

    def _sync_navigation_chapters(self, title: str) -> List[str]:
        """Return the reader-local chapter order for Prev/Next.

        When the current chapter is still in downloaded-state, the live
        downloaded list is authoritative. If remove-after-read has already
        dropped the visible chapter, keep the previous reader-local order as
        the anchor and merge in any newly downloaded/prefetched chapters.
        """
        downloaded = [
            str(ch) for ch in self.app.app_state.get_downloaded_chapters(title)
        ]
        current = str(self._chapter)
        if current in downloaded:
            self._navigation_chapters = downloaded
            return self._navigation_chapters

        merged = []
        for chapter in self._navigation_chapters:
            chapter = str(chapter)
            if chapter not in merged:
                merged.append(chapter)
        if current not in merged:
            self._insert_navigation_chapter(merged, current)
        for chapter in downloaded:
            chapter = str(chapter)
            if chapter not in merged:
                self._insert_navigation_chapter(merged, chapter)
        self._navigation_chapters = merged
        return self._navigation_chapters

    def _insert_navigation_chapter(self, sequence: List[str], chapter: str):
        """Insert a newly discovered chapter into reader-local order."""
        key = _chapter_sort_key(chapter)
        if key is None:
            sequence.append(chapter)
            return

        for idx, existing in enumerate(sequence):
            existing_key = _chapter_sort_key(existing)
            if existing_key is not None and existing_key > key:
                sequence.insert(idx, chapter)
                return
        sequence.append(chapter)

    def _navigation_neighbor(self, direction: int,
                             title: Optional[str] = None) -> Optional[str]:
        """Find the nearest downloaded neighbor in the local navigation
        sequence. Removed stale entries are skipped, but the current chapter
        itself may remain as the anchor after remove-after-read."""
        if not self._manga or self._chapter is None:
            return None
        title = title if title is not None else self._manga.get("title", "")
        sequence = self._sync_navigation_chapters(title)
        current = str(self._chapter)
        try:
            idx = sequence.index(current)
        except ValueError:
            return None

        downloaded = set(
            str(ch) for ch in self.app.app_state.get_downloaded_chapters(title)
        )
        step = 1 if direction > 0 else -1
        i = idx + step
        while 0 <= i < len(sequence):
            chapter = sequence[i]
            if chapter in downloaded:
                return chapter
            i += step
        return None

    # -- Reader prefetch (issue #107) ------------------------------------
    def _maybe_prefetch_next(self):
        """Quietly queue the immediate next available chapter for a
        manual-mode manga so Next keeps working without leaving the
        reader. Setting-gated and cache-first; every failure path is a
        silent no-op so it can never block or disrupt reading."""
        try:
            if not self.app.config.reader_prefetch_enabled:
                return
            if not self._manga or self._chapter is None:
                return
            # Manual mode only. Auto-mode manga already queue ahead on
            # their own schedule, so prefetch here would be redundant.
            if (self._manga.get("mode") or "auto") != "manual":
                return
            title = self._manga.get("title", "")
            if not title:
                return
            # Never fire background network requests while the app knows
            # it is offline -- download_chapter would only surface a
            # download_error the user did not ask for.
            worker = self.app.worker
            if getattr(worker, "_is_offline", None) and worker._is_offline():
                return
            entry = self._resolve_next_chapter_entry()
            if entry is _PREFETCH_SKIP:
                return
            if entry is None:
                # Missing cache: optionally force one bounded lookup.
                self._maybe_prefetch_fallback(title)
                return
            self._queue_prefetch(entry)
        except Exception:
            # Best-effort: a prefetch failure must never interrupt reading.
            pass

    def _resolve_next_chapter_entry(self):
        """Return the cached available-chapters entry for the immediate
        next chapter after the current one, or None. Skips when that
        chapter is already downloaded (Next already works)."""
        title = self._manga.get("title", "")
        available = self.app.app_state.get_available_chapters(title)
        if not available:
            return None
        current = _chapter_sort_key(self._chapter)
        if current is None:
            return _PREFETCH_SKIP
        downloaded = set(self.app.app_state.get_downloaded_chapters(title))
        best_key = None
        best_entry = None
        for entry in available:
            key = _chapter_sort_key(entry.get("number"))
            if key is None or key <= current:
                continue
            if best_key is None or key < best_key:
                best_key = key
                best_entry = entry
        if best_entry is None:
            # A cached list that stops at/before the current chapter may be
            # stale, so let the bounded fallback refresh it once.
            return None
        # The immediate next chapter is already on disk -- nothing to do.
        if str(best_entry.get("number")) in downloaded:
            return _PREFETCH_SKIP
        return best_entry

    def _queue_prefetch(self, entry):
        """Route a cached chapter entry through the shared download queue,
        mirroring the manual Detail-page flow so output format, Kindle
        delivery, naming, post-processing and partial tolerance all match.
        The worker dedups the task id, so a queued/active chapter is a
        no-op there too."""
        try:
            from ...downloader import ChapterWithSource
            from ...scrapers.base import Chapter
        except Exception:
            return
        number = str(entry.get("number", ""))
        if not number:
            return
        title = self._manga.get("title", "")
        # Guard the double-check race: a completion could have landed
        # between resolve and here.
        if self.app.app_state.is_chapter_downloaded(title, number):
            return
        url = entry.get("url") or entry.get("source_url") or ""
        if not url:
            return
        source = entry.get("source", "")
        source_url = entry.get("source_url") or url
        is_backup = bool(entry.get("is_backup", False))
        ch_title = entry.get("title") or ""
        base = Chapter(number=number, title=ch_title, url=url, date=None)
        chapter = ChapterWithSource(base, source, source_url, is_backup=is_backup)

        cfg = self.app.config
        from ...email_settings import kindle_delivery_settings

        self.app.worker.download_chapter(
            manga=self._manga, chapter=chapter,
            output_dir=cfg.download_dir,
            output_format=cfg.output_format,
            state=self.app.app_state,
            kindle_cfg=kindle_delivery_settings(cfg, self._manga),
            naming_template=cfg.get("delivery.naming_template"),
            post_processing=cfg.get("delivery.post_processing"),
            allow_partial=cfg.partial_enabled,
            partial_threshold=cfg.partial_threshold,
            # Never delete-after-send here: this copy is fetched to be
            # read next, so it must stay on disk.
            delete_after_send=False,
        )

    def _maybe_prefetch_fallback(self, title):
        """Missing-cache fallback: kick off one forced check so the next
        chapter metadata can be populated, then retry on the matching
        completion. The per-chapter attempt key bounds source failures to
        one lookup for each reader load."""
        key = "%s:%s" % (title, self._chapter)
        if (self._prefetch_fallback_key is not None
                or self._prefetch_fallback_attempted_key == key):
            return
        worker = self.app.worker
        if getattr(worker, "_is_offline", None) and worker._is_offline():
            return
        self._prefetch_fallback_key = key
        self._prefetch_fallback_attempted_key = key
        try:
            worker.check_updates(
                [self._manga], self.app.app_state, self.app.config, force=True,
                request_id=key)
        except Exception:
            self._prefetch_fallback_key = None

    def _on_check_complete(self, data):
        """A fallback check we started finished -- its results are cached
        now, so retry the prefetch and reveal Next if a successor
        appeared. Ignores checks we did not initiate."""
        if (self._prefetch_fallback_key is None
                or data.get("request_id") != self._prefetch_fallback_key):
            return
        self._prefetch_fallback_key = None
        if not self._manga:
            return
        self._refresh_next_controls()
        entry = self._resolve_next_chapter_entry()
        if entry is not None and entry is not _PREFETCH_SKIP:
            self._queue_prefetch(entry)

    def _on_download_complete(self, data):
        """A background download finished. If it belongs to the manga we
        are reading, refresh the Next controls so a chapter prefetched
        mid-read becomes navigable without reloading the current one."""
        if not self._manga:
            return
        if data.get("title") != self._manga.get("title", ""):
            return
        self._refresh_next_controls()

    def _next_footer_label(self, next_chapter):
        """Caption for the continuous-mode footer button, resolved from
        reader navigation at build/refresh time -- never captured -- so
        a chapter prefetched mid-read shows its real number once
        _refresh_next_controls reveals the button (issue #107)."""
        if next_chapter is not None:
            return f"Next: Chapter {next_chapter} >>"
        return "Next Chapter >>"

    def _refresh_next_controls(self):
        """Re-evaluate whether a next downloaded chapter exists and
        show/hide the Next controls accordingly. Safe to call after a
        background download completes -- it never rebuilds the reader and
        tolerates widgets already torn down by a reload."""
        if not self._manga or self._chapter is None:
            return
        title = self._manga.get("title", "")
        next_ch = self._navigation_neighbor(+1, title)
        has_next = next_ch is not None
        if self._next_footer_btn is not None:
            try:
                self._next_footer_btn.setText(
                    self._next_footer_label(next_ch))
            except RuntimeError:
                pass
        for widget in (self._next_btn, self._next_footer):
            if widget is None:
                continue
            try:
                widget.setVisible(has_next)
            except RuntimeError:
                # Widget was deleted by a chapter reload; the fresh build
                # will re-evaluate visibility itself.
                pass
