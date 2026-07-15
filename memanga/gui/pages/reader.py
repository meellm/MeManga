"""
Reader page - Built-in manga reader with keyboard shortcuts and zoom.
Three layouts: continuous vertical scroll, single page, two-up spreads.
"""

import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget,
)
from PySide6.QtGui import QPixmap, QImage, QKeyEvent, QShortcut
from PySide6.QtCore import Qt, QByteArray, QBuffer, QEvent, QObject, QTimer

from .base import BasePage
from .. import theme as T


def _extract_images_from_file(filepath: Path) -> List[QImage]:
    """Extract images from a downloaded chapter file."""
    suffix = filepath.suffix.lower()
    images = []

    if suffix in (".cbz", ".zip"):
        with zipfile.ZipFile(filepath, "r") as zf:
            names = sorted([n for n in zf.namelist() if not n.startswith("__")])
            for name in names:
                ext = Path(name).suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    data = zf.read(name)
                    img = QImage()
                    img.loadFromData(data)
                    if not img.isNull():
                        images.append(img)

    elif suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(str(filepath))
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                # Make a deep copy since pix.samples is transient
                images.append(img.copy())
            doc.close()
        except ImportError:
            try:
                from PIL import Image as PILImage
                import pikepdf
                pdf = pikepdf.open(str(filepath))
                for page in pdf.pages:
                    for img_key in page.images:
                        raw = page.images[img_key]
                        pil_img = PILImage.open(io.BytesIO(raw.get_raw_stream_buffer()))
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        qimg = QImage()
                        qimg.loadFromData(buf.getvalue())
                        if not qimg.isNull():
                            images.append(qimg)
                pdf.close()
            except Exception:
                pass

    elif suffix == ".epub":
        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                names = sorted(zf.namelist())
                for name in names:
                    ext = Path(name).suffix.lower()
                    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        data = zf.read(name)
                        img = QImage()
                        img.loadFromData(data)
                        if not img.isNull():
                            images.append(img)
        except Exception:
            pass

    return images


def _chapter_sort_key(number) -> Optional[float]:
    """Numeric sort key for a chapter number, or None when it can't be
    parsed. Used by the reader prefetch (issue #107) to find the
    immediate next chapter without assuming the cache is pre-sorted.
    Mirrors Chapter.numeric's extraction so labels like "Chapter 2" or
    "2 Part 1" resolve too, but yields None instead of 0.0 when nothing
    numeric is found -- an unparseable chapter must skip prefetch, not
    sort as chapter zero."""
    if number is None:
        return None
    try:
        return float(str(number).strip())
    except (ValueError, TypeError):
        pass
    match = re.search(r"(\d+\.?\d*)", str(number))
    if match:
        return float(match.group(1))
    return None


_PREFETCH_SKIP = object()


def _extract_images_from_folder(folder: Path) -> List[QImage]:
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    images = []
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in extensions])
    for f in files:
        try:
            img = QImage(str(f))
            if not img.isNull():
                images.append(img)
        except Exception:
            pass
    return images


class ReaderPage(BasePage):
    """Manga reader with continuous / single-page / two-up layouts,
    keyboard shortcuts and zoom."""

    ZOOM_MIN = 0.5
    ZOOM_MAX = 2.5
    ZOOM_STEP = 0.25
    DEFAULT_MAX_WIDTH = 800
    # Issue #45: scroll ratio at which a chapter counts as read. The
    # slack below 1.0 covers the spacing + "Next chapter" button row
    # appended after the last page, so finishing the final page is
    # enough without having to pixel-perfectly hit the bottom.
    READ_THRESHOLD = 0.98
    # Issue #32: the three reader layouts the toolbar toggle cycles
    # between. "double" is the issue-#24 two-up view, now paged.
    VIEW_MODES = ("continuous", "single", "double")
    PAGED_MODES = ("single", "double")

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._chapter = None
        # Issue #104: concrete file/folder the current chapter was loaded
        # from, recorded in _find_and_load_chapter so the "remove after
        # reading" cleanup deletes exactly what the reader opened.
        self._artifact_path: Optional[Path] = None
        self._images: List[QImage] = []
        self._page_labels: list = []
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
        self._images.clear()
        self._page_labels.clear()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self._manga:
                self.app.show_page("detail", manga=self._manga)
            return
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_in()
        elif key == Qt.Key.Key_Minus:
            self._zoom_out()
        elif key == Qt.Key.Key_F:
            self._toggle_fit_width()
        elif key == Qt.Key.Key_N:
            self._go_next_chapter()
        elif key == Qt.Key.Key_P:
            self._go_prev_chapter()
        elif self._view_mode in self.PAGED_MODES and key in (
                Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self._page_step(+1)
        elif self._view_mode in self.PAGED_MODES and key in (
                Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self._page_step(-1)
        elif self._view_mode in self.PAGED_MODES and key == Qt.Key.Key_Home:
            self._go_to_page(0)
        elif self._view_mode in self.PAGED_MODES and key == Qt.Key.Key_End:
            self._go_to_page(len(self._images) - 1)
        elif key == Qt.Key.Key_Down:
            self._scroll_vertical(+1)
        elif key == Qt.Key.Key_Up:
            self._scroll_vertical(-1)
        elif key == Qt.Key.Key_Right:
            self._arrow_horizontal(+1)
        elif key == Qt.Key.Key_Left:
            self._arrow_horizontal(-1)
        else:
            super().keyPressEvent(event)

    # ── Arrow-key navigation (issue #43) ──────────────────────────────
    # The page itself holds keyboard focus (StrongFocus + setFocus in
    # on_show), so the QScrollArea never sees arrow keys natively —
    # they must be handled here alongside the other shortcuts.

    def _scroll_vertical(self, direction: int):
        """Up/Down: scroll half a viewport per press."""
        if self._scroll is None:
            return
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.value() + direction * max(40, bar.pageStep() // 2))

    def _arrow_horizontal(self, direction: int):
        """Left/Right in continuous mode: pan when zoomed content
        overflows horizontally, otherwise jump to the prev/next chapter
        (mirrors P/N). Paged modes never reach here — their Left/Right
        turn pages in keyPressEvent (issue #32)."""
        if self._scroll is not None:
            bar = self._scroll.horizontalScrollBar()
            if bar.maximum() > 0:
                bar.setValue(bar.value() + direction * max(40, bar.pageStep() // 2))
                return
        if direction > 0:
            self._go_next_chapter()
        else:
            self._go_prev_chapter()

    # ── Page-by-page navigation (issue #32) ───────────────────────────
    # Only active in the "single" and "double" layouts. Up/Down keep
    # their scroll meaning so a zoomed-in page can still be read top to
    # bottom; Left/Right/PageUp/PageDown/Space/Home/End move between
    # pages (or spreads in two-up).

    def _page_step(self, direction: int):
        """Advance one page (single) or one spread (double)."""
        step = 2 if self._view_mode == "double" else 1
        self._go_to_page(self._current_page + direction * step)

    def _go_to_page(self, index: int):
        if not self._images:
            return
        index = max(0, min(len(self._images) - 1, index))
        if self._view_mode == "double":
            index -= index % 2  # spreads stay aligned to fixed pairs
        if index == self._current_page:
            return
        self._current_page = index
        self._rebuild_images()
        # Each new page starts at its top-left corner, like turning a
        # physical page — leftover scroll from a zoomed previous page
        # would otherwise open the new one mid-panel.
        if self._scroll is not None:
            self._scroll.verticalScrollBar().setValue(0)
            self._scroll.horizontalScrollBar().setValue(0)

    def _zoom_in(self):
        if self._zoom_level < self.ZOOM_MAX:
            self._zoom_level += self.ZOOM_STEP
            self._rebuild_images()

    def _zoom_out(self):
        if self._zoom_level > self.ZOOM_MIN:
            self._zoom_level -= self.ZOOM_STEP
            self._rebuild_images()

    # ── Reader layout (issues #24, #32) ───────────────────────────────
    # Three layouts: continuous scroll, single page, two-up spreads.
    # The choice persists per manga so a webtoon can stay continuous
    # while a print manga stays single-page.

    def _resolve_view_mode(self) -> str:
        """Layout for the current manga: its config entry's
        ``reader_mode``, else the global ``gui.reader_view_mode``, else
        the legacy ``gui.reader_dual_page`` boolean (issue #24)."""
        title = (self._manga or {}).get("title", "")
        for entry in self.app.config.get("manga", []) or []:
            if entry.get("title") == title:
                mode = entry.get("reader_mode")
                if mode in self.VIEW_MODES:
                    return mode
                break
        mode = self.app.config.get("gui.reader_view_mode")
        if mode in self.VIEW_MODES:
            return mode
        if self.app.config.get("gui.reader_dual_page", False):
            return "double"
        return "continuous"

    def _set_view_mode(self, mode: str):
        """Switch layout, persist it for this manga, and re-render."""
        if mode not in self.VIEW_MODES or mode == self._view_mode:
            return
        if self._view_mode == "continuous" and self._scroll is not None \
                and self._images:
            # Carry the reading position over: estimate the current page
            # from the scroll ratio, same as the progress bar does.
            sb = self._scroll.verticalScrollBar()
            ratio = sb.value() / max(1, sb.maximum())
            self._current_page = min(len(self._images) - 1,
                                     int(ratio * len(self._images)))
        self._view_mode = mode

        def _store(entry):
            entry["reader_mode"] = mode
        title = (self._manga or {}).get("title", "")
        if not (title and self.app.config.update_manga(title, _store)):
            # Manga not in config (e.g. removed mid-read): fall back to
            # the global default so the choice still sticks.
            self.app.config.set("gui.reader_view_mode", mode)
            self.app.config.save()

        self._refresh_mode_btns()
        self._rebuild_images()
        if self._scroll is not None:
            self._scroll.verticalScrollBar().setValue(0)
            self._scroll.horizontalScrollBar().setValue(0)

    def _refresh_mode_btns(self):
        """Accent-tint the active layout's toolbar button."""
        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        for mode, (btn, icon_name) in self._mode_btns.items():
            color = (T.tokens()["accent.primary"] if mode == self._view_mode
                     else T.tokens()["text.t_2"])
            btn.setIcon(_ic(icon_name, color, 16))
            btn.setIconSize(QSize(16, 16))

    # ── Ctrl+wheel zoom (issue #16) ──────────────────────────────────────
    # The scroll area's viewport eats wheel events for native scrolling.
    # We install ourselves as an event filter on the viewport AFTER the
    # scroll area is created in _load_chapter, so we can peek at wheel
    # events and consume them when Ctrl is held. Otherwise we let them
    # fall through to the scroll area's default page-scroll handling.

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.Wheel:
            mods = event.modifiers()
            is_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            # On macOS, Cmd+wheel is the conventional zoom trigger.
            # KeyboardModifier.MetaModifier is Cmd on macOS, Win key on
            # other OSes — both unusual enough to safely treat as zoom.
            is_cmd = bool(mods & Qt.KeyboardModifier.MetaModifier)
            if is_ctrl or is_cmd:
                # angleDelta().y() is in 1/8 degree units; positive = up.
                # We also fall back to pixelDelta for high-precision
                # touchpads (some Apple drivers fire pixelDelta only).
                delta = event.angleDelta().y()
                if delta == 0:
                    delta = event.pixelDelta().y()
                if delta > 0:
                    self._zoom_in()
                elif delta < 0:
                    self._zoom_out()
                event.accept()
                return True  # consumed — don't let viewport scroll too

        # ── Click-and-drag pan (issue #21) ──────────────────────────────
        # When zoomed in, let users drag the page around to navigate
        # parts that don't fit the viewport. Works in both directions —
        # vertical pan complements wheel scroll, horizontal pan is the
        # only way to reach off-screen content when ZOOM is >= ~1.0.
        elif et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and self._scroll is not None:
                self._pan_active = True
                self._pan_start_x = event.position().x()
                self._pan_start_y = event.position().y()
                self._pan_start_h = self._scroll.horizontalScrollBar().value()
                self._pan_start_v = self._scroll.verticalScrollBar().value()
                self._scroll.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                # Don't consume — let the press through in case child
                # widgets want it (none do today, but safer).
        elif et == QEvent.Type.MouseMove:
            if getattr(self, "_pan_active", False) and self._scroll is not None:
                dx = event.position().x() - self._pan_start_x
                dy = event.position().y() - self._pan_start_y
                hbar = self._scroll.horizontalScrollBar()
                vbar = self._scroll.verticalScrollBar()
                hbar.setValue(int(self._pan_start_h - dx))
                vbar.setValue(int(self._pan_start_v - dy))
                event.accept()
                return True
        elif et == QEvent.Type.MouseButtonRelease:
            if getattr(self, "_pan_active", False):
                self._pan_active = False
                if self._scroll is not None:
                    self._scroll.viewport().setCursor(self._idle_cursor())

        return super().eventFilter(obj, event)

    def _idle_cursor(self):
        """OpenHand when content overflows (panning available), else
        ArrowCursor (no point hinting at drag if there's nothing to pan).
        """
        if self._scroll is None:
            return Qt.CursorShape.ArrowCursor
        h = self._scroll.horizontalScrollBar()
        v = self._scroll.verticalScrollBar()
        if h.maximum() > 0 or v.maximum() > 0:
            return Qt.CursorShape.OpenHandCursor
        return Qt.CursorShape.ArrowCursor

    # ── Touchpad pinch zoom (issue #16) ──────────────────────────────────
    # Two delivery paths converge here:
    #   1. QGestureEvent (Windows/Linux + Qt's gesture framework) — fires
    #      via grabGesture(PinchGesture) in __init__. Pinch.totalScaleFactor
    #      is multiplicative: 1.10 = 10% bigger than gesture start.
    #   2. QNativeGestureEvent (macOS trackpad) — fires per OS gesture
    #      tick. event.value() is a small additive delta (~0.04 per tick).
    # We accumulate deltas until they cross ZOOM_STEP, then snap.

    def event(self, ev):
        if ev.type() == QEvent.Type.Gesture:
            from PySide6.QtWidgets import QGesture
            pinch = ev.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                self._handle_pinch(pinch)
                ev.accept()
                return True
        elif ev.type() == QEvent.Type.NativeGesture:
            # macOS trackpad gestures
            try:
                gt = ev.gestureType()
            except AttributeError:
                gt = None
            # Qt.NativeGestureType.ZoomNativeGesture is the pinch on Mac.
            if gt == Qt.NativeGestureType.ZoomNativeGesture:
                self._pinch_accum += float(ev.value())
                self._flush_pinch_accum()
                ev.accept()
                return True
        return super().event(ev)

    def _handle_pinch(self, pinch):
        """Snap a PinchGesture's `totalScaleFactor` onto our discrete
        ZOOM_STEP ladder. Starts fresh on each gesture, so users always
        feel deterministic step behavior even after multiple pinches.
        """
        from PySide6.QtWidgets import QGesture
        state = pinch.state()
        if state == Qt.GestureState.GestureStarted:
            self._pinch_baseline = self._zoom_level
            return
        # On Update/Finished, compute target from baseline * totalScaleFactor.
        if state in (Qt.GestureState.GestureUpdated, Qt.GestureState.GestureFinished):
            try:
                factor = float(pinch.totalScaleFactor())
            except Exception:
                factor = 1.0
            baseline = getattr(self, "_pinch_baseline", self._zoom_level)
            target = max(self.ZOOM_MIN, min(self.ZOOM_MAX, baseline * factor))
            # Snap to the nearest ZOOM_STEP so we don't constantly
            # re-render at fractional sizes.
            stepped = round(target / self.ZOOM_STEP) * self.ZOOM_STEP
            if abs(stepped - self._zoom_level) >= self.ZOOM_STEP / 2:
                self._zoom_level = stepped
                self._rebuild_images()

    def _flush_pinch_accum(self):
        """Drain the macOS native-gesture accumulator one ZOOM_STEP at a time."""
        # value() is additive per tick on macOS; positive = zoom in.
        while self._pinch_accum >= self.ZOOM_STEP / 4:
            self._zoom_in()
            self._pinch_accum -= self.ZOOM_STEP / 4
        while self._pinch_accum <= -self.ZOOM_STEP / 4:
            self._zoom_out()
            self._pinch_accum += self.ZOOM_STEP / 4

    def _toggle_fit_width(self):
        self._fit_width = not self._fit_width
        self._rebuild_images()

    def _rebuild_images(self):
        if not self._scroll or not self._images:
            return

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

        if hasattr(self, "_zoom_label") and self._zoom_label:
            self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")
        self._update_progress_display()

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
        # chapter is finished. Runs after the read set is updated so read
        # progress survives even if the deletion fails.
        self._remove_after_read(title, str(self._chapter))
        # Tell other pages (Library, Detail) to repaint without
        # waiting for the next navigation.
        self.app.events.publish("chapter_read", {
            "title": title, "chapter": str(self._chapter),
        })

    def _remove_after_read(self, title: str, chapter: str):
        """Delete the just-read chapter's local artifact and drop it from
        downloaded-state when the "remove chapters after reading" setting
        is on (issue #104).

        Read-state is intentionally left intact — only the downloaded
        record and the on-disk file/folder go away, so the Detail row
        returns to the Download state. Deletion failures are non-fatal:
        the chapter stays marked downloaded and a notification is logged
        instead of desyncing state from disk or crashing the reader.
        """
        if not self.app.config.get("reader.remove_after_read", False):
            return
        path = self._artifact_path
        if path is None:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            # If the file is already gone, treat that as success and let
            # the downloaded-state removal below reconcile with disk.
        except OSError as exc:
            self.app.app_state.add_notification(
                "error",
                f"Couldn't remove {title} Chapter {chapter} after reading: {exc}",
            )
            return
        self._artifact_path = None
        self.app.app_state.remove_downloaded_chapter(title, chapter)

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

    def _render_images(self):
        # Total width the spread is allowed to occupy.
        if self._fit_width:
            try:
                max_w = min(self._scroll.width() - 40, 1200)
            except Exception:
                max_w = self.DEFAULT_MAX_WIDTH
            if max_w < 300:
                max_w = self.DEFAULT_MAX_WIDTH
        else:
            max_w = self.DEFAULT_MAX_WIDTH

        max_w = int(max_w * self._zoom_level)

        def _scaled_pixmap(qimg, target_w):
            """Scale qimg so its width fits target_w (with zoom factored in)."""
            w, h = qimg.width(), qimg.height()
            if w > target_w:
                ratio = target_w / w
                new_w, new_h = int(w * ratio), int(h * ratio)
            else:
                new_w = int(w * self._zoom_level)
                new_h = int(h * self._zoom_level)
            return QPixmap.fromImage(qimg).scaled(
                new_w, new_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        # Paged layouts center the (short) content in the viewport;
        # continuous keeps everything pinned to the top of the scroll.
        if self._image_layout is not None:
            if self._view_mode in self.PAGED_MODES:
                self._image_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self._image_layout.setAlignment(
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        if self._view_mode == "continuous":
            # ── Continuous (default): all pages stacked vertically ──
            for qimg in self._images:
                lbl = QLabel()
                lbl.setPixmap(_scaled_pixmap(qimg, max_w))
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._image_layout.addWidget(lbl)
                self._page_labels.append(lbl)
            return

        # ── Paged layouts (issue #32): only the current page/spread ──
        self._current_page = max(0, min(len(self._images) - 1,
                                        self._current_page))
        if self._view_mode == "double":
            self._current_page -= self._current_page % 2

        if self._view_mode == "single":
            lbl = QLabel()
            lbl.setPixmap(_scaled_pixmap(self._images[self._current_page], max_w))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._image_layout.addWidget(lbl)
            self._page_labels.append(lbl)
            return

        # ── Two-up (issues #24, #32): one spread, two pages side-by-side
        # (or one if the chapter ends on an odd page). Allocate half
        # max_w per side so the spread as a whole stays inside the
        # viewport.
        per_side = max(120, (max_w - 8) // 2)
        i = self._current_page
        spread = QHBoxLayout()
        spread.setSpacing(4)
        spread.setContentsMargins(0, 0, 0, 0)
        spread.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for j in (0, 1):
            if i + j >= len(self._images):
                break
            lbl = QLabel()
            lbl.setPixmap(_scaled_pixmap(self._images[i + j], per_side))
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop | (
                Qt.AlignmentFlag.AlignRight if j == 0 else Qt.AlignmentFlag.AlignLeft
            ))
            spread.addWidget(lbl)
            self._page_labels.append(lbl)

        self._image_layout.addLayout(spread)

    def _load_chapter(self):
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

        # ── Load images ──
        self._images = self._find_and_load_chapter()
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

    def _find_and_load_chapter(self) -> List[QImage]:
        # Issue #111: the downloader saves under the *sanitized* title
        # folder and formats chapter labels for sorting ("2 Part 1" ->
        # "2.01"), so the lookup must mirror those exact conventions.
        # Raw title/label locations are kept as fallbacks for downloads
        # that predate this fix.
        from ...downloader import _format_chapter_number, _sanitize_filename

        # Reset before resolving so a failed load can't leave a stale path
        # pointing at the previous chapter (issue #104).
        self._artifact_path = None
        title = self._manga.get("title", "")
        ch = str(self._chapter)
        download_dir = Path(self.app.config.download_dir)

        labels = []
        for label in (_format_chapter_number(ch), ch, f"{ch}.0"):
            if label not in labels:
                labels.append(label)

        manga_dirs = []
        for d in (download_dir / _sanitize_filename(title), download_dir / title):
            if d.is_dir() and d not in manga_dirs:
                manga_dirs.append(d)

        for manga_dir in manga_dirs:
            for label in labels:
                # Sanitize the full base name, not just the title — the
                # downloader builds "{title} - Chapter {chapter}" first
                # and sanitizes the result (incl. the length cap).
                base = _sanitize_filename(f"{title} - Chapter {label}")
                for ext in [".pdf", ".epub", ".cbz", ".zip"]:
                    filepath = manga_dir / f"{base}{ext}"
                    if filepath.exists():
                        self._artifact_path = filepath
                        return _extract_images_from_file(filepath)

                folder = manga_dir / f"Chapter {label}"
                if folder.is_dir():
                    self._artifact_path = folder
                    return _extract_images_from_folder(folder)

        # Fallback: scan directories for anything chapter-shaped
        for manga_dir in manga_dirs:
            for f in manga_dir.iterdir():
                if f.is_file() and any(
                    f"chapter {label.lower()}" in f.stem.lower() for label in labels
                ):
                    self._artifact_path = f
                    return _extract_images_from_file(f)
                if f.is_dir() and any(label in f.name for label in labels):
                    self._artifact_path = f
                    return _extract_images_from_folder(f)

        return []

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
        kindle_cfg = None
        global_email_on = (cfg.delivery_mode == "email" and cfg.email_enabled)
        if global_email_on and self._manga.get("send_to_kindle", True):
            try:
                from ...config import get_app_password
                kindle_cfg = dict(
                    kindle_email=cfg.get("email.kindle_email"),
                    sender_email=cfg.get("email.sender_email"),
                    app_password=get_app_password(cfg),
                    smtp_server=cfg.get("email.smtp_server", "smtp.gmail.com"),
                    smtp_port=cfg.get("email.smtp_port", 587),
                )
            except Exception:
                kindle_cfg = None

        self.app.worker.download_chapter(
            manga=self._manga, chapter=chapter,
            output_dir=cfg.download_dir,
            output_format=cfg.output_format,
            state=self.app.app_state, kindle_cfg=kindle_cfg,
            naming_template=cfg.get("delivery.naming_template"),
            post_processing=cfg.get("delivery.post_processing"),
            allow_partial=cfg.partial_enabled,
            partial_threshold=cfg.partial_threshold,
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
