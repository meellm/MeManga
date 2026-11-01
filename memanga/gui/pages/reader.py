"""
Reader page - Built-in manga reader with keyboard shortcuts and zoom.
Three layouts: continuous vertical scroll, single page, two-up spreads.
"""

import time
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget,
)
from PySide6.QtGui import QPixmap, QShortcut
from PySide6.QtCore import (Qt, QByteArray, QBuffer, QObject, QRect, QSize,
                            QTimer)

from ...image_limits import exceeds_pixel_limit
from .base import BasePage
from .reader_input import ReaderInputMixin
from .reader_navigation import ReaderNavigationMixin
from .reader_view_modes import ReaderViewModeMixin
from .reader_pages import (PageLoader, PageRef, PixmapCache, display_size,
                           index_chapter_file, index_chapter_folder)
from .. import theme as T
from .. import trash


def _is_inside_download_dir(candidate: Path, download_dir: Path) -> bool:
    """True when *candidate* resolves to a location strictly inside
    *download_dir*.

    Validates that the candidate resolves strictly inside the download
    directory. The download root itself does not qualify. Either path
    may be non-existent; resolution is done without requiring existence.
    """
    try:
        resolved = candidate.resolve()
        root = download_dir.resolve()
    except OSError:
        return False
    return resolved != root and resolved.is_relative_to(root)


class ReaderPage(ReaderInputMixin, ReaderNavigationMixin,
                 ReaderViewModeMixin, BasePage):
    """Manga reader with continuous / single-page / two-up layouts,
    keyboard shortcuts and zoom. Input handling lives in reader_input,
    chapter Prev/Next and prefetch in reader_navigation, the layouts and
    page turning in reader_view_modes, page indexing and decoding in
    reader_pages."""

    ZOOM_MIN = 0.5
    ZOOM_MAX = 2.5
    ZOOM_STEP = 0.25
    DEFAULT_MAX_WIDTH = 800
    # Issue #45: scroll ratio at which a chapter counts as read. The
    # slack below 1.0 covers the spacing + "Next chapter" button row
    # appended after the last page, so finishing the final page is
    # enough without having to pixel-perfectly hit the bottom.
    READ_THRESHOLD = 0.98
    # Issue #389: pages (or spreads, in two-up) decoded ahead of and
    # behind the visible ones, and the memory budget for scaled pages
    # kept around for quick revisits. Everything else stays undecoded.
    PAGE_PREFETCH_AHEAD = 3
    PAGE_PREFETCH_BEHIND = 1
    PAGE_CACHE_BYTES = 192 * 1024 * 1024
    # Longest the UI waits for a page decode that is still reading a
    # finished chapter's file when leaving it. Past that, remove-after-read
    # is kept and retried every REMOVAL_RETRY_MS until the file is free.
    REMOVAL_WAIT_S = 2.0
    REMOVAL_RETRY_MS = 250

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._chapter = None
        # Issue #104: concrete file/folder the current chapter was loaded
        # from, recorded in _find_and_load_chapter so the "remove after
        # reading" cleanup deletes exactly what the reader opened.
        self._artifact_path: Optional[Path] = None
        # Issue #389: the open chapter's pages as lightweight refs (order
        # + natural size). Pixels are decoded lazily off the UI thread.
        self._images: List[PageRef] = []
        self._page_labels: list = []
        # Issue #389: worker-thread decoding. Results come back through a
        # queued connection, so _on_page_ready always runs on the GUI
        # thread. The slot map ties a page index to its on-screen label;
        # the offsets are each continuous-mode label's top edge.
        self._page_loader = PageLoader(self)
        self._page_loader.page_ready.connect(
            self._on_page_ready, Qt.ConnectionType.QueuedConnection)
        self._page_cache = PixmapCache(self.PAGE_CACHE_BYTES)
        self._page_slots: Dict[int, QLabel] = {}
        self._page_target_w = self.DEFAULT_MAX_WIDTH
        self._page_offsets: List[int] = []
        self._page_keep: Tuple[int, int] = (0, -1)
        self._shown_pages: Set[int] = set()
        self._failed_pages: Set[int] = set()
        # Issue #389: remove-after-read for a finished chapter, deferred
        # until the reader leaves it: (title, chapter, artifact path).
        self._pending_removal: Optional[Tuple[str, str, Path]] = None
        # Left chapters whose file a page decode was still reading at the
        # deadline; the timer retries them, deleting only once idle.
        self._removal_queue: List[Tuple[str, str, Path]] = []
        self._removal_timer = QTimer(self)
        self._removal_timer.setInterval(self.REMOVAL_RETRY_MS)
        self._removal_timer.timeout.connect(self._retry_pending_removals)
        self._zoom_level = 1.0
        self._fit_width = True
        # Issue #32: reader layout — "continuous" (vertical scroll, all
        # pages stacked), "single" (one page at a time) or "double"
        # (two-up spreads, one spread at a time). Resolved per manga in
        # _load_chapter; this is just the cold default.
        self._view_mode = "continuous"
        # First visible page index in the paged modes (always even in
        # "double" so spreads stay aligned to the same page pairs).
        self._current_page = 0
        self._content: Optional[QWidget] = None
        self._scroll = None
        self._image_layout = None
        self._page_indicator = None
        self._mode_btns = {}
        # Issue #45: set once the current chapter has been marked read,
        # so the scroll handler only fires the state write + event once.
        self._read_marked = False
        # Issue #107: reader prefetch of the next manual-mode chapter.
        # Handles to the Next controls live here so a prefetched
        # download finishing mid-read can reveal them without reloading
        # the chapter; _prefetch_fallback_key marks a prefetch that is
        # waiting on a forced source lookup (cache-miss fallback).
        self._next_btn = None
        self._next_footer = None
        self._next_footer_btn = None
        # Issue #104/#107: navigation needs a stable anchor while the
        # current chapter remains visible after remove-after-read drops it
        # from downloaded-state. New downloads are merged into this list so
        # dynamic Next controls still reveal prefetched successors.
        self._navigation_chapters: List[str] = []
        self._prefetch_fallback_key = None
        self._prefetch_fallback_attempted_key = None
        self.app.events.subscribe("download_complete",
                                  self._on_download_complete)
        self.app.events.subscribe("check_complete", self._on_check_complete)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ── Touchpad pinch zoom (issue #16) ──────────────────────────────
        # Grab the high-level PinchGesture on Windows/Linux. On macOS the
        # OS sends NativeGesture events instead — those are caught in
        # event() below. Both paths converge on _apply_zoom_factor().
        self.grabGesture(Qt.GestureType.PinchGesture)
        # Pinch accumulator: native-gesture deltas are tiny per-tick so we
        # batch them up before snapping to the next ZOOM_STEP.
        self._pinch_accum = 0.0

        # ── Click-and-drag pan state (issue #21) ─────────────────────────
        self._pan_active = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_start_h = 0
        self._pan_start_v = 0

    def on_show(self, **kwargs):
        manga = kwargs.get("manga")
        chapter = kwargs.get("chapter")
        if manga:
            self._manga = manga
        if chapter:
            self._chapter = chapter
        self._zoom_level = 1.0
        self._fit_width = True
        if self._manga and self._chapter:
            self._load_chapter()
            title = self._manga.get("title", "")
            if title:
                # Cursor (most-recent) tracking (issue #18). The
                # per-chapter read set is only updated once the user
                # scrolls to the end of the chapter (issue #45) — see
                # _mark_current_read.
                self.app.app_state.set_reading_progress(title, str(self._chapter))
        self.setFocus()

    def on_hide(self):
        # Issue #106: any navigation away from the reader (Back button,
        # Escape, sidebar — everything routed through show_page) is a
        # save point for the in-chapter resume position.
        self.save_reading_position()
        self._reset_page_loading()
        self._finish_pending_removal()
        self._images.clear()
        self._page_labels.clear()

    def _rebuild_images(self):
        if not self._scroll or not self._images:
            return

        # Issue #389: zoom / fit-width in continuous mode only changes
        # page sizes, so the placeholders are resized in place. Recreating
        # every page widget of a long chapter stalled the UI.
        if not (self._view_mode == "continuous"
                and self._resize_continuous_pages()):
            self._rebuild_page_widgets()

        if hasattr(self, "_zoom_label") and self._zoom_label:
            self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")
        self._update_progress_display()

    def _rebuild_page_widgets(self):
        # Drain the layout completely — labels AND the dual-page HBox
        # spread layouts. Previously we only deleted labels, which left
        # orphaned QHBoxLayout items behind on every dual<->single flip.
        for lbl in self._page_labels:
            try:
                lbl.deleteLater()
            except Exception:
                pass
        self._page_labels.clear()
        if self._image_layout is not None:
            i = self._image_layout.count() - 1
            while i >= 0:
                item = self._image_layout.itemAt(i)
                w = item.widget() if item else None
                if w:
                    w.deleteLater()
                    self._image_layout.removeWidget(w)
                elif item and item.layout():
                    self._clear_sub_layout(item.layout())
                    self._image_layout.removeItem(item)
                elif item:
                    self._image_layout.removeItem(item)
                i -= 1

        self._render_images()

    def _clear_sub_layout(self, layout):
        """Recursively drain a layout's children + delete widgets."""
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget() if it else None
            if w:
                w.deleteLater()
            elif it and it.layout():
                self._clear_sub_layout(it.layout())

    def _on_scroll(self, _value):
        """Update the sticky bottom progress bar from scroll position."""
        # Issue #32: in the paged layouts scrolling only moves within
        # the current page — progress is tracked per page in
        # _update_progress_display instead.
        if self._view_mode in self.PAGED_MODES:
            return
        self._update_page_window()
        try:
            sb = self._scroll.verticalScrollBar()
            mx = max(1, sb.maximum())
            ratio = sb.value() / mx
            page_n = max(1, min(len(self._images), int(ratio * len(self._images)) + 1))
            self._progress_left.setText(f"Page {page_n} of {len(self._images)}")
            self._progress_track.setValue(int(ratio * 1000))
            self._progress_pct.setText(f"{int(ratio * 100)}%")
            if self._page_indicator:
                self._page_indicator.setText(f"{page_n} / {len(self._images)}")
            # Issue #45: only flip the chapter to read once the user has
            # actually scrolled (or jumped) to the end of it.
            if sb.maximum() > 0 and ratio >= self.READ_THRESHOLD:
                self._mark_current_read()
        except Exception:
            pass

    def _update_progress_display(self):
        """Sync the page indicator + bottom progress bar to the reading
        position. Continuous mode derives it from the scroll offset; the
        paged modes (issue #32) from the visible page index — which also
        marks the chapter read once the final page is on screen."""
        if self._view_mode not in self.PAGED_MODES:
            self._on_scroll(0)  # ratio is re-read from the scrollbar
            return
        total = len(self._images)
        if not total:
            return
        first = self._current_page
        last = min(total - 1, first + 1) if self._view_mode == "double" else first
        try:
            if self._page_indicator:
                self._page_indicator.setText(f"{first + 1} / {total}")
            ratio = (last + 1) / total
            self._progress_left.setText(f"Page {first + 1} of {total}")
            self._progress_track.setValue(int(ratio * 1000))
            self._progress_pct.setText(f"{int(ratio * 100)}%")
        except (AttributeError, RuntimeError):
            pass
        if last >= total - 1:
            self._mark_current_read()

    def _mark_current_read(self):
        """Mark the current chapter read (issue #45: only called when the
        user reaches the end). The per-chapter set powers the Library's
        "X/N read" sub-line and the Detail chapter row badge (issue #18).
        """
        if self._read_marked or not self._manga or not self._chapter:
            return
        title = self._manga.get("title", "")
        if not title:
            return
        self._read_marked = True
        self.app.app_state.mark_chapter_read(title, str(self._chapter))
        # Issue #106: a finished chapter should reopen from its first
        # page, not keep resuming at the saved end-of-chapter position.
        self.app.app_state.clear_reader_position(title, str(self._chapter))
        # Issue #104: optionally discard the local file now that the
        # chapter is finished. Issue #389: pages are decoded from that
        # file on demand, so the deletion waits until the reader leaves
        # the chapter (_finish_pending_removal). The read set is already
        # updated, so read progress survives even if the deletion fails.
        if (self.app.config.get("reader.remove_after_read", False)
                and self._artifact_path is not None):
            self._pending_removal = (title, str(self._chapter),
                                     self._artifact_path)
        # Tell other pages (Library, Detail) to repaint without
        # waiting for the next navigation.
        self.app.events.publish("chapter_read", {
            "title": title, "chapter": str(self._chapter),
        })

    def _remove_after_read(self, title: str, chapter: str,
                           path: Optional[Path]):
        """Move the just-read chapter's local artifact to the system trash
        and drop it from downloaded-state when the "remove chapters after
        reading" setting is on (issue #104).

        Read-state is intentionally left intact — only the downloaded
        record and the on-disk file/folder go away, so the Detail row
        returns to the Download state. Issue #393: the file goes to the
        trash, never deleted for good, so a chapter finished by accident
        can be restored. If the trash can't take it, the file is kept,
        the chapter stays marked downloaded and a notification is logged
        instead of desyncing state from disk or crashing the reader.
        """
        if not self.app.config.get("reader.remove_after_read", False):
            return
        if path is None:
            return
        # If the file is already gone, treat that as success and let the
        # downloaded-state removal below reconcile with disk.
        if path.exists() or path.is_symlink():
            try:
                location = trash.move_to_trash(path)
            except OSError as exc:
                self.app.app_state.add_notification(
                    "error",
                    f"Couldn't move {title} Chapter {chapter} to the "
                    f"{trash.trash_name()} after reading, so it was kept: "
                    f"{exc}",
                )
                return
            self.app.app_state.add_notification(
                "system",
                f"Moved {title} Chapter {chapter} to the "
                f"{trash.trash_name()} after reading.",
                f"Now in the {trash.trash_name()} at: {location}"
                if location else None,
            )
        if self._artifact_path == path:
            self._artifact_path = None
        self.app.app_state.remove_downloaded_chapter(title, chapter)
        # Issue #389: the removal can finish after the reader was left
        # (a page decode still held the file), so pages already showing
        # the chapter as downloaded must hear about it.
        self.app.events.publish("chapter_removed", {
            "title": title, "chapter": chapter,
        })

    def _mark_read_if_unscrollable(self):
        """A chapter that fits entirely in the viewport never scrolls, so
        the end-of-scroll threshold can't fire — but the user is already
        seeing all of it, which is as "finished" as it gets."""
        # Paged layouts (issue #32) mark read from the page index in
        # _update_progress_display — a single fitting page there just
        # means the user is on ONE page, not done with the chapter.
        if self._view_mode in self.PAGED_MODES:
            return
        if self._read_marked or self._scroll is None or not self._images:
            return
        viewport_h = self._scroll.viewport().height()
        content = self._scroll.widget()
        if viewport_h <= 0 or content is None:
            return
        if content.sizeHint().height() <= viewport_h:
            self._mark_current_read()

    # ── In-chapter resume position (issue #106) ───────────────────────
    # Separate from the chapter cursor (`reading_progress.last_chapter`)
    # and the read set (issue #45): remembers *where inside* a chapter
    # the user stopped, so reopening that chapter picks up there. Saved
    # on every way out of the reader — Back/Escape/sidebar via on_hide,
    # Prev/Next via _navigate_chapter, app close via MeMangaApp.closeEvent
    # — and cleared once the chapter is finished, so completed chapters
    # reopen from the start instead of forever near the end.

    def save_reading_position(self):
        """Persist (or clear) the resume position for the open chapter.
        Positions at the very start or at/over the completion threshold
        aren't worth resuming — the start is the default and the end
        means the chapter was finished — so those clear instead."""
        if not self._manga or not self._chapter or not self._images:
            return
        title = self._manga.get("title", "")
        if not title:
            return
        state = self.app.app_state
        chapter = str(self._chapter)

        if self._view_mode in self.PAGED_MODES:
            last = self._current_page + (1 if self._view_mode == "double"
                                         else 0)
            if self._current_page <= 0 or last >= len(self._images) - 1:
                state.clear_reader_position(title, chapter)
                return
            state.set_reader_position(title, chapter, mode=self._view_mode,
                                      page_index=self._current_page)
            return

        if self._scroll is None:
            return
        try:
            sb = self._scroll.verticalScrollBar()
            maximum, value = sb.maximum(), sb.value()
        except RuntimeError:
            return  # scroll area already torn down
        if maximum <= 0:
            # Chapter fits the viewport whole — nothing to resume.
            state.clear_reader_position(title, chapter)
            return
        ratio = value / maximum
        if ratio <= 0.0 or ratio >= self.READ_THRESHOLD:
            state.clear_reader_position(title, chapter)
            return
        state.set_reader_position(title, chapter, mode="continuous",
                                  scroll_ratio=ratio)

    def _restore_reader_position(self):
        """Re-apply a previously saved in-chapter position. Paged modes
        jump straight to the saved page/spread before the first render;
        continuous mode defers the scroll one event-loop turn so the
        freshly-built layout has a scrollbar range to scroll within.
        Everything is clamped, cross-converted between page index and
        scroll ratio when the layout changed since the save, and ignored
        at/over the completion threshold — a restore must never flip the
        chapter to read by itself, and stale data (page count changed,
        chapter re-downloaded) must stay harmless."""
        title = (self._manga or {}).get("title", "")
        if not title or not self._images:
            return
        pos = self.app.app_state.get_reader_position(title, str(self._chapter))
        if not pos:
            return
        total = len(self._images)
        page_index = pos.get("page_index")
        scroll_ratio = pos.get("scroll_ratio")

        if self._view_mode in self.PAGED_MODES:
            if page_index is None:
                # Saved from continuous mode: estimate the page from the
                # scroll ratio, same mapping _set_view_mode uses.
                if scroll_ratio is None:
                    return
                page_index = int(float(scroll_ratio) * total)
            index = max(0, min(total - 1, int(page_index)))
            if self._view_mode == "double":
                index -= index % 2  # spreads stay aligned to fixed pairs
            last = index + (1 if self._view_mode == "double" else 0)
            if index <= 0 or last >= total - 1:
                return
            self._current_page = index
            return

        if scroll_ratio is None:
            # Saved from a paged mode: page N of M lands at ratio N/M.
            if page_index is None:
                return
            scroll_ratio = int(page_index) / total
        ratio = min(1.0, max(0.0, float(scroll_ratio)))
        if ratio <= 0.0 or ratio >= self.READ_THRESHOLD:
            return
        # The scrollbar range is still 0 while _load_chapter builds the
        # layout — defer one turn, same trick as _mark_read_if_unscrollable.
        chapter = str(self._chapter)
        QTimer.singleShot(
            0, lambda: self._apply_saved_scroll_ratio(chapter, ratio))

    def _apply_saved_scroll_ratio(self, chapter: str, ratio: float):
        """Deferred half of the continuous-mode restore."""
        # The user may have navigated on before the timer fired; only
        # apply to the chapter the ratio was saved against.
        if str(self._chapter) != chapter or self._scroll is None:
            return
        try:
            sb = self._scroll.verticalScrollBar()
            if sb.maximum() > 0:
                sb.setValue(int(ratio * sb.maximum()))
        except RuntimeError:
            pass  # scroll area torn down before the timer fired

    def _page_width_budget(self) -> int:
        """Total width the page or spread may occupy, zoom included."""
        if self._fit_width:
            try:
                max_w = min(self._scroll.width() - 40, 1200)
            except Exception:
                max_w = self.DEFAULT_MAX_WIDTH
            if max_w < 300:
                max_w = self.DEFAULT_MAX_WIDTH
        else:
            max_w = self.DEFAULT_MAX_WIDTH

        return int(max_w * self._zoom_level)

    # ── Lazy page loading (issue #389) ────────────────────────────────
    # Opening a chapter only indexes it (page order + header sizes).
    # Pages are decoded and scaled on the loader's worker threads, and
    # only around the reading position: the visible pages first, then
    # PAGE_PREFETCH_AHEAD ahead and PAGE_PREFETCH_BEHIND behind. Pages
    # that leave that window drop their pixmap; a byte-bounded cache
    # keeps recent ones for quick revisits. Every chapter load starts a
    # new loader token, so late results from the previous chapter are
    # ignored.

    def _page_label(self, index: int, target_w: int) -> QLabel:
        """Placeholder label for one page, sized like the final pixmap
        and filled at once when the page is already cached."""
        lbl = QLabel()
        lbl.setFixedSize(self._placeholder_size(self._images[index],
                                                target_w))
        self._page_slots[index] = lbl
        cached = self._page_cache.get((index, target_w, self._zoom_level))
        if cached is not None:
            self._set_page_pixmap(index, lbl, cached)
        elif index in self._failed_pages:
            self._show_page_failed(lbl, index)
        return lbl

    def _placeholder_size(self, ref: PageRef, target_w: int) -> QSize:
        # A page over the pixel limit is never shown, so its declared size
        # mustn't stretch the layout either.
        if (ref.width > 0 and ref.height > 0
                and not exceeds_pixel_limit(ref.width, ref.height)):
            return display_size(ref.width, ref.height, target_w,
                                self._zoom_level)
        # No usable header size: reserve a typical page shape until
        # the decoded page sets the real one.
        return QSize(target_w, int(target_w * 1.5))

    def _resize_continuous_pages(self) -> bool:
        """Resize the continuous-mode placeholders for a new zoom or
        fit-width without recreating them; the scroll offset is kept,
        as with a rebuild. False when the continuous layout isn't built
        (e.g. coming from a paged layout), so the caller rebuilds it."""
        if (not self._page_offsets
                or len(self._page_labels) != len(self._images)):
            return False
        max_w = self._page_width_budget()
        self._page_target_w = max_w
        self._shown_pages.clear()
        spacing = max(0, self._image_layout.spacing())
        top = self._page_offsets[0]
        try:
            for index, lbl in enumerate(self._page_labels):
                lbl.clear()
                lbl.setFixedSize(self._placeholder_size(self._images[index],
                                                        max_w))
                self._page_offsets[index] = top
                cached = self._page_cache.get(
                    (index, max_w, self._zoom_level))
                if cached is not None:
                    self._set_page_pixmap(index, lbl, cached)
                elif index in self._failed_pages:
                    self._show_page_failed(lbl, index)
                top += lbl.height() + spacing
        except RuntimeError:
            return False  # a label is already gone: rebuild instead
        self._update_page_window()
        return True

    def _visible_page_range(self) -> Optional[Tuple[int, int, int]]:
        """(first, last, step) of the pages on screen; step is the page
        count of one paging move, so prefetch walks whole spreads."""
        total = len(self._images)
        if self._view_mode in self.PAGED_MODES:
            first = self._current_page
            last = first + (1 if self._view_mode == "double" else 0)
            return first, min(total - 1, last), last - first + 1
        if not self._page_offsets or self._scroll is None:
            return None
        try:
            top = self._scroll.verticalScrollBar().value()
            bottom = top + max(1, self._scroll.viewport().height())
        except RuntimeError:
            return None  # scroll area torn down
        first = max(0, bisect_right(self._page_offsets, top) - 1)
        last = max(first, bisect_left(self._page_offsets, bottom) - 1)
        return first, min(total - 1, last), 1

    def _update_page_window(self):
        """Request the pages around the reading position (visible ones
        first) and release the pixmaps of pages far from it."""
        if not self._images or not self._page_slots:
            return
        visible = self._visible_page_range()
        if visible is None:
            return
        first, last, step = visible
        total = len(self._images)
        ahead_end = min(total, last + 1 + self.PAGE_PREFETCH_AHEAD * step)
        behind_start = max(0, first - self.PAGE_PREFETCH_BEHIND * step)
        order = (list(range(first, last + 1))
                 + list(range(last + 1, ahead_end))
                 + list(range(first - 1, behind_start - 1, -1)))

        target_w, zoom = self._page_target_w, self._zoom_level
        wanted = []
        for index in order:
            if index in self._failed_pages or index in self._shown_pages:
                continue
            key = (index, target_w, zoom)
            wanted.append(key)
            cached = self._page_cache.get(key)
            if cached is not None:
                label = self._page_slots.get(index)
                if label is not None:
                    self._set_page_pixmap(index, label, cached)
                continue
            self._page_loader.request(index, self._images[index],
                                      target_w, zoom)
        self._page_loader.cancel_outside(wanted)

        # One extra step of slack on each side, so a page sitting on the
        # window edge doesn't flip between loaded and released.
        keep_lo = max(0, behind_start - step)
        keep_hi = ahead_end - 1 + step
        self._page_keep = (keep_lo, keep_hi)
        for index in [i for i in self._shown_pages
                      if not keep_lo <= i <= keep_hi]:
            self._shown_pages.discard(index)
            label = self._page_slots.get(index)
            if label is not None:
                try:
                    label.clear()
                except RuntimeError:
                    pass  # deleted by a rebuild

    def _on_page_ready(self, token: int, index: int, target_w: int,
                       zoom: float, image):
        """A worker finished a page (GUI thread, via queued signal)."""
        key = (index, target_w, zoom)
        if not self._page_loader.finish(token, key):
            return  # from a previous chapter
        current = (target_w == self._page_target_w
                   and zoom == self._zoom_level)
        label = self._page_slots.get(index) if current else None
        if image.isNull():
            self._failed_pages.add(index)
            if label is not None:
                self._show_page_failed(label, index)
            return
        pixmap = QPixmap.fromImage(image)
        self._page_cache.put(key, pixmap)
        keep_lo, keep_hi = self._page_keep
        if label is not None and keep_lo <= index <= keep_hi:
            self._set_page_pixmap(index, label, pixmap)

    def _set_page_pixmap(self, index: int, label: QLabel, pixmap: QPixmap):
        try:
            if label.size() != pixmap.size():
                # Header size was missing or off: take the real one.
                label.setFixedSize(pixmap.size())
                self._recompute_page_offsets()
            label.setPixmap(pixmap)
        except RuntimeError:
            return  # deleted by a rebuild
        self._shown_pages.add(index)

    def _recompute_page_offsets(self):
        if self._view_mode != "continuous" or not self._page_offsets:
            return
        spacing = max(0, self._image_layout.spacing())
        top = self._page_offsets[0]
        for index in range(len(self._page_offsets)):
            self._page_offsets[index] = top
            label = self._page_slots.get(index)
            top += (label.height() if label is not None else 0) + spacing

    def _show_page_failed(self, label: QLabel, index: int):
        try:
            label.setStyleSheet(
                f"color: {T.FG_MUTED}; font-size: {T.FONT_SIZE_SM}pt;")
            label.setWordWrap(True)
            ref = (self._images[index] if 0 <= index < len(self._images)
                   else None)
            if ref is not None and exceeds_pixel_limit(ref.width, ref.height):
                label.setText(f"Page {index + 1} is too large to show "
                              f"({ref.width} x {ref.height} pixels).")
            else:
                label.setText(f"Page {index + 1} couldn't be loaded.")
            # A small page's slot can be too small for the message: grow
            # it until the message fits, wrapped to the page width.
            label.ensurePolished()
            metrics = label.fontMetrics()
            pad = 16
            width = max(label.width(), min(
                metrics.horizontalAdvance(label.text()) + pad,
                max(label.width(), self._page_target_w)))
            text = metrics.boundingRect(
                QRect(0, 0, max(1, width - pad), 10000),
                Qt.TextFlag.TextWordWrap, label.text())
            height = max(label.height(), text.height() + pad)
            if (width, height) != (label.width(), label.height()):
                label.setFixedSize(width, height)
                self._recompute_page_offsets()
        except RuntimeError:
            pass  # deleted by a rebuild

    def _reset_page_loading(self):
        """Drop the open chapter's decode jobs, cache and pixmaps."""
        self._page_loader.reset()
        self._page_cache.clear()
        for label in self._page_slots.values():
            try:
                label.clear()
            except RuntimeError:
                pass
        self._page_slots.clear()
        self._shown_pages.clear()
        self._failed_pages.clear()
        self._page_offsets = []
        self._page_keep = (0, -1)

    def _finish_pending_removal(
            self, reopening: Optional[Tuple[str, str]] = None):
        """Run the remove-after-read that _mark_current_read deferred,
        now that the reader is letting go of that chapter. Callers cancel
        its page jobs first; a decode still reading the file gets up to
        REMOVAL_WAIT_S to finish. The file is only deleted once no decode
        reads it; past the deadline the removal stays queued and the
        retry timer finishes it. Runs at most once per finished chapter.

        *reopening* is the (title, chapter) about to be opened: a queued
        removal for it is handed back to _pending_removal first, so the
        file stays until that chapter is left again."""
        pending, self._pending_removal = self._pending_removal, None
        if pending is not None and pending not in self._removal_queue:
            self._removal_queue.append(pending)
        if reopening is not None:
            for item in list(self._removal_queue):
                if (item[0], item[1]) == reopening:
                    self._removal_queue.remove(item)
                    self._pending_removal = item
        self._process_removal_queue(self.REMOVAL_WAIT_S, leaving=True)

    def _retry_pending_removals(self):
        """Retry timer (GUI thread): never blocks, only checks."""
        self._process_removal_queue(0, leaving=False)

    def _process_removal_queue(self, wait: float, leaving: bool):
        deadline = time.monotonic() + wait
        for item in list(self._removal_queue):
            title, chapter, path = item
            if not leaving and self._images and path == self._artifact_path:
                # Opened again since: it goes when the reader leaves it.
                self._removal_queue.remove(item)
                if self._pending_removal is None:
                    self._pending_removal = item
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if not self._page_loader.wait_idle(remaining, path):
                continue  # still being read: keep it for the retry
            self._removal_queue.remove(item)
            self._remove_after_read(title, chapter, path)
        if not self._removal_queue:
            self._removal_timer.stop()
        elif not self._removal_timer.isActive():
            self._removal_timer.start()

    def shutdown_page_loader(self):
        """Stop the page decode workers and finish a deferred
        remove-after-read (app close)."""
        self._page_loader.shutdown()
        self._finish_pending_removal()
        self._removal_timer.stop()
        # Nothing can retry after the app closes: the chapter stays on
        # disk and downloaded (state matches disk), and the user is told.
        for title, chapter, _path in self._removal_queue:
            self.app.app_state.add_notification(
                "error",
                f"Couldn't move {title} Chapter {chapter} to the "
                f"{trash.trash_name()} after reading: the file was still "
                "in use, so it was kept.",
            )
        self._removal_queue.clear()

    def _load_chapter(self):
        # Issue #389: no decode job or pixmap of the previous chapter
        # survives into this one, and its deferred remove-after-read runs
        # now that nothing reads its file any more. The chapter being
        # opened keeps its file even when its removal was still queued.
        self._reset_page_loading()
        self._finish_pending_removal(reopening=(
            (self._manga or {}).get("title", ""), str(self._chapter)))
        # Tear down previous content
        if self._content:
            self._content.deleteLater()
            self._content = None

        # Issue #45: each chapter load starts with an unread gate, even
        # when navigating Prev/Next within the reader.
        self._read_marked = False
        # Issue #107: the previous chapter's Next controls die with
        # self._content above — drop the handles so a stray refresh
        # can't poke deleted widgets.
        self._next_btn = None
        self._next_footer = None
        self._next_footer_btn = None
        self._prefetch_fallback_key = None
        self._prefetch_fallback_attempted_key = None
        # Issue #32: every chapter opens on its first page, in whatever
        # layout this manga last used (or the global/legacy fallback) —
        # unless a resume position was saved for it (issue #106), which
        # _restore_reader_position re-applies once the images are in.
        self._current_page = 0
        self._view_mode = self._resolve_view_mode()

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Ensure this widget has a layout
        if not self.layout():
            QVBoxLayout(self)
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.layout().setSpacing(0)
        self.layout().addWidget(self._content)

        title = self._manga.get("title", "Unknown")

        # ── Reader header (matches HTML spec.screens.reader.reader_header) ──
        top = QFrame()
        top.setStyleSheet(
            f"background-color: {T.tokens()['surfaces.bg_1']};"
            f"border-bottom: 1px solid {T.tokens()['surfaces.border']};"
        )
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(24, 12, 24, 12)
        top_layout.setSpacing(10)

        back_btn = QPushButton("‹ Back")
        back_btn.setProperty("variant", "ghost")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.app.show_page("detail", manga=self._manga))
        top_layout.addWidget(back_btn)

        # Title: '{manga_title} · Chapter {n} — {chapter_title}'
        title_text = (
            f"<b style='color:{T.tokens()['text.t_1']}'>{title}</b>  "
            f"<span style='color:{T.tokens()['text.t_3']}'>·  Chapter {self._chapter}</span>"
        )
        title_label = QLabel(title_text)
        title_label.setStyleSheet(f"font-size: 13pt;")
        top_layout.addWidget(title_label)

        top_layout.addStretch()

        # Chapter navigation
        prev_ch = self._navigation_neighbor(-1, title)
        next_ch = self._navigation_neighbor(+1, title)

        if prev_ch is not None:
            prev_btn = QPushButton("‹ Prev")
            prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            prev_btn.clicked.connect(lambda checked=False, c=prev_ch: self._navigate_chapter(c))
            top_layout.addWidget(prev_btn)

        # Issue #107: the Next button always exists (hidden without a
        # successor) so a prefetched chapter finishing mid-read can
        # reveal it via _refresh_next_controls instead of a full reload.
        # It resolves its target on click, so no chapter is captured.
        self._next_btn = QPushButton("Next ›")
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.clicked.connect(
            lambda checked=False: self._go_next_chapter())
        self._next_btn.setVisible(next_ch is not None)
        top_layout.addWidget(self._next_btn)

        # ── Layout toggle (issues #24, #32) ─────────────────────────────
        # Three iconified buttons (same style as the zoom +/- chip):
        # continuous scroll, single page, two-up. The active layout's
        # icon is accent-tinted in _refresh_mode_btns.
        self._mode_btns = {}
        for mode, icon_name, tip in (
            ("continuous", "view_continuous", "Continuous vertical scroll"),
            ("single", "view_single", "Single page at a time"),
            ("double", "view_dual", "Two-page spreads"),
        ):
            btn = QPushButton()
            btn.setFixedSize(36, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda checked=False, m=mode: self._set_view_mode(m))
            self._mode_btns[mode] = (btn, icon_name)
            top_layout.addWidget(btn)
        self._refresh_mode_btns()

        # Zoom chip
        zoom_minus = QPushButton("−")
        zoom_minus.setFixedSize(28, 28)
        zoom_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_minus.clicked.connect(self._zoom_out)
        top_layout.addWidget(zoom_minus)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
            f"color: {T.tokens()['text.t_3']}; padding: 0 8px;"
        )
        top_layout.addWidget(self._zoom_label)

        zoom_plus = QPushButton("+")
        zoom_plus.setFixedSize(28, 28)
        zoom_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_plus.clicked.connect(self._zoom_in)
        top_layout.addWidget(zoom_plus)

        # Page count indicator: '{cur} / {total}' (mono t_3)
        self._page_indicator = QLabel("— / —")
        self._page_indicator.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 11pt;"
            f"color: {T.tokens()['text.t_3']}; padding-left: 12px;"
        )
        top_layout.addWidget(self._page_indicator)

        content_layout.addWidget(top)

        # MangaDex chapters credit MangaDex and the scanlation group, and a
        # chapter from a group that asked for removal is not shown.
        from ...downloader import _get_sources_from_manga
        from ...scrapers.mangadex import removed_group_ids
        # The saved file's own group record wins over the cached list,
        # which a later check may have refilled without that group (#400).
        entry = self.app.app_state.get_chapter_groups(title, self._chapter)
        if not entry:
            available = self.app.app_state.get_available_chapters(title)
            entry = next((c for c in available
                          if str(c.get("number")) == str(self._chapter)), {})
        sources = _get_sources_from_manga(self._manga)
        source = entry.get("source") or (sources[0]["source"] if sources else "")
        is_mangadex = source in ("mangadex.org", "api.mangadex.org")
        unavailable = is_mangadex and bool(
            removed_group_ids(self.app.config) & set(entry.get("group_ids", [])))
        if is_mangadex:
            names = entry.get("group_names", [])
            credit = "MangaDex" + (" · " + ", ".join(names) if names else "")
            credit_label = QLabel(credit)
            credit_label.setTextFormat(Qt.TextFormat.PlainText)
            credit_label.setProperty("role", "hint")
            credit_label.setContentsMargins(24, 6, 24, 6)
            content_layout.addWidget(credit_label)

        # ── Load images ──
        self._images = [] if unavailable else self._find_and_load_chapter()
        self._page_labels.clear()

        if not self._images:
            from ...downloader import _sanitize_filename
            download_dir = self.app.config.download_dir
            # Issue #111: report the sanitized folder — the one the
            # downloader actually writes to — not the raw title.
            manga_dir = Path(download_dir) / _sanitize_filename(
                self._manga.get("title", ""))
            empty = QLabel(
                f"Could not load chapter {self._chapter} images.\n\n"
                f"Looked in: {manga_dir}\n"
                f"The file may not have been downloaded yet."
            )
            empty.setStyleSheet(f"color: {T.FG_MUTED}; font-size: {T.FONT_SIZE_SM}pt;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if unavailable:
                empty.setText("This chapter is unavailable at the scanlation group's request. Recheck the series for current chapters.")
            empty.setWordWrap(True)
            content_layout.addWidget(empty, 1)
            return

        # Issue #106: land back where the user left this chapter. Sits
        # after the empty-images bail-out above, so a chapter whose file
        # was cleaned up never touches (or trips over) its stale position.
        self._restore_reader_position()

        self._page_indicator.setText(
            f"{int(self._zoom_level * 100)}%  |  {len(self._images)} pages"
        )

        # ── Scrollable image area (reader_body) ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # Issue #21: allow horizontal scrollbar when zoomed images
        # overflow the viewport. AsNeeded keeps it hidden at fit-width.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Issue #49: no setStyleSheet here. A selector-less widget
        # stylesheet cascades into every descendant and overrode the
        # accent background of the "Next chapter" button, leaving its
        # dark on_primary label invisible on bg_0. The app QSS already
        # paints ReaderPage bg_0 and keeps scroll areas transparent.
        # Issue #16 + #21: intercept Ctrl/Cmd+wheel for zoom AND track
        # mouse press/move for click-and-drag pan. Plain wheel events
        # fall through to default scrolling.
        self._scroll.viewport().installEventFilter(self)
        # Track movement even when no button is held — needed for the
        # OpenHand-on-hover affordance to update as content overflows.
        self._scroll.viewport().setMouseTracking(True)
        self._scroll.viewport().setCursor(self._idle_cursor())
        # Refresh cursor whenever the scrollable area changes size
        # (e.g. after zoom rebuilds the images).
        self._scroll.horizontalScrollBar().rangeChanged.connect(
            lambda *_: self._scroll.viewport().setCursor(self._idle_cursor())
        )
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._scroll.viewport().setCursor(self._idle_cursor())
        )
        # Issue #389: the layout settling or the window resizing changes
        # which pages are on screen.
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._update_page_window())

        scroll_content = QWidget()
        self._image_layout = QVBoxLayout(scroll_content)
        self._image_layout.setSpacing(1)
        self._image_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(scroll_content)

        self._render_images()

        # "Next Chapter" button at bottom — continuous mode only: the
        # paged layouts re-render per page, so an in-flow footer would
        # show under every single page rather than after the last one.
        # Issue #107: built even without a successor (hidden) so a
        # prefetch completion can flip it visible without a reload.
        if self._view_mode == "continuous":
            next_frame = QWidget()
            next_frame_layout = QHBoxLayout(next_frame)
            next_frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            next_chapter_btn = QPushButton(
                self._next_footer_label(next_ch))
            next_chapter_btn.setProperty("class", "accent")
            next_chapter_btn.setFixedHeight(40)
            next_chapter_btn.setFixedWidth(250)
            next_chapter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            next_chapter_btn.clicked.connect(
                lambda checked=False: self._go_next_chapter()
            )
            next_frame_layout.addWidget(next_chapter_btn)
            self._image_layout.addSpacing(T.PAD_XL)
            self._image_layout.addWidget(next_frame)
            next_frame.setVisible(next_ch is not None)
            self._next_footer = next_frame
            self._next_footer_btn = next_chapter_btn

        content_layout.addWidget(self._scroll, 1)

        # ── Sticky bottom progress (reader_progress) ──
        # Tracks scroll position vs. document height.
        progress_bar = QFrame()
        progress_bar.setStyleSheet(
            f"background-color: {T.tokens()['surfaces.bg_1']};"
            f"border-top: 1px solid {T.tokens()['surfaces.border']};"
        )
        pb_l = QHBoxLayout(progress_bar)
        pb_l.setContentsMargins(24, 10, 24, 10)
        pb_l.setSpacing(12)

        self._progress_left = QLabel(f"Page 1 of {len(self._images)}")
        self._progress_left.setStyleSheet(f"color: {T.tokens()['text.t_2']}; font-size: 11pt;")
        pb_l.addWidget(self._progress_left)

        from PySide6.QtWidgets import QProgressBar
        self._progress_track = QProgressBar()
        self._progress_track.setRange(0, 1000)  # finer granularity for scroll
        self._progress_track.setValue(0)
        self._progress_track.setTextVisible(False)
        self._progress_track.setFixedHeight(4)
        pb_l.addWidget(self._progress_track, 1)

        self._progress_pct = QLabel("0%")
        self._progress_pct.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
            f"color: {T.tokens()['text.t_3']};"
        )
        pb_l.addWidget(self._progress_pct)

        content_layout.addWidget(progress_bar)

        # Wire scroll to the progress bar so it updates as the user scrolls.
        sb = self._scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        # Initial paint.
        self._update_progress_display()
        # Issue #45: after the layout settles, a chapter short enough to
        # fit the viewport whole is immediately fully visible — the
        # scroll threshold can never fire for it.
        QTimer.singleShot(0, self._mark_read_if_unscrollable)
        # Issue #107: with the chapter on screen, quietly prepare the
        # next one for manual-mode manga (setting-gated, cache-first).
        self._maybe_prefetch_next()

    def _find_and_load_chapter(self) -> List[PageRef]:
        # Issue #111: the downloader saves under the *sanitized* title
        # folder and formats chapter labels for sorting ("2" -> "0002.000",
        # "2 Part 1" -> "0002_Part 01"), so the lookup must mirror those
        # exact conventions. Raw title locations and older label forms
        # ("2", "2.01") are kept as fallbacks for earlier downloads.
        from ...downloader import _sanitize_filename
        from ...downloader.naming import (DEFAULT_NAMING_TEMPLATE,
                                          _chapter_base_name,
                                          _chapter_filename_labels)

        # Reset before resolving so a failed load can't leave a stale path
        # pointing at the previous chapter (issue #104).
        self._artifact_path = None
        title = self._manga.get("title", "")
        ch = str(self._chapter)
        download_dir = Path(self.app.config.download_dir)

        labels = _chapter_filename_labels(ch)

        manga_dirs = []
        for d in (download_dir / _sanitize_filename(title), download_dir / title):
            if (
                d.is_dir()
                and d not in manga_dirs
                and _is_inside_download_dir(d, download_dir)
            ):
                manga_dirs.append(d)

        for manga_dir in manga_dirs:
            for label in labels:
                # Current downloads shorten a long title so the chapter
                # text stays whole (labels[0] is the current form). Older
                # versions sanitized the full "{title} - Chapter {label}"
                # and cut its end at the length cap; keep that for the
                # older label forms (and the raw label it shares).
                bases = []
                if label == labels[0]:
                    bases.append(_chapter_base_name(
                        DEFAULT_NAMING_TEMPLATE, title, label))
                if label != labels[0] or label == ch:
                    bases.append(
                        _sanitize_filename(f"{title} - Chapter {label}"))
                for base in dict.fromkeys(bases):
                    for ext in [".pdf", ".epub", ".cbz", ".zip"]:
                        filepath = manga_dir / f"{base}{ext}"
                        if filepath.exists():
                            self._artifact_path = filepath
                            return index_chapter_file(filepath)

                # The downloader only writes a single-component
                # "Chapter <label>" folder, so require that exact shape
                # before loading legacy image folders.
                folder = manga_dir / f"Chapter {label}"
                if (
                    folder.parent == manga_dir
                    and _is_inside_download_dir(folder, download_dir)
                    and folder.is_dir()
                ):
                    self._artifact_path = folder
                    return index_chapter_folder(folder)

        # Fallback: scan directories for anything chapter-shaped
        for manga_dir in manga_dirs:
            for f in manga_dir.iterdir():
                if f.is_file() and any(
                    f"chapter {label.lower()}" in f.stem.lower() for label in labels
                ):
                    self._artifact_path = f
                    return index_chapter_file(f)
                if f.is_dir() and any(label in f.name for label in labels):
                    self._artifact_path = f
                    return index_chapter_folder(f)

        return []
