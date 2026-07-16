"""
Reader page - Built-in manga reader with keyboard shortcuts and zoom.
Three layouts: continuous vertical scroll, single page, two-up spreads.
"""

import io
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
        # Tell other pages (Library, Detail) to repaint without
        # waiting for the next navigation.
        self.app.events.publish("chapter_read", {
            "title": title, "chapter": str(self._chapter),
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
        # Issue #32: every chapter opens on its first page, in whatever
        # layout this manga last used (or the global/legacy fallback).
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
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
        except ValueError:
            idx = -1

        if idx > 0:
            prev_ch = downloaded[idx - 1]
            prev_btn = QPushButton("‹ Prev")
            prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            prev_btn.clicked.connect(lambda checked=False, c=prev_ch: self._navigate_chapter(c))
            top_layout.addWidget(prev_btn)

        if idx >= 0 and idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            next_btn = QPushButton("Next ›")
            next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            next_btn.clicked.connect(lambda checked=False, c=next_ch: self._navigate_chapter(c))
            top_layout.addWidget(next_btn)

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
        if self._view_mode == "continuous" and 0 <= idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            next_frame = QWidget()
            next_frame_layout = QHBoxLayout(next_frame)
            next_frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            next_chapter_btn = QPushButton(f"Next: Chapter {next_ch} >>")
            next_chapter_btn.setProperty("class", "accent")
            next_chapter_btn.setFixedHeight(40)
            next_chapter_btn.setFixedWidth(250)
            next_chapter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            next_chapter_btn.clicked.connect(
                lambda checked=False, c=next_ch: self._navigate_chapter(c)
            )
            next_frame_layout.addWidget(next_chapter_btn)
            self._image_layout.addSpacing(T.PAD_XL)
            self._image_layout.addWidget(next_frame)

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

    def _find_and_load_chapter(self) -> List[QImage]:
        # Issue #111: the downloader saves under the *sanitized* title
        # folder and formats chapter labels for sorting ("2 Part 1" ->
        # "2.01"), so the lookup must mirror those exact conventions.
        # Raw title/label locations are kept as fallbacks for downloads
        # that predate this fix.
        from ...downloader import _format_chapter_number, _sanitize_filename

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
                        return _extract_images_from_file(filepath)

                folder = manga_dir / f"Chapter {label}"
                if folder.is_dir():
                    return _extract_images_from_folder(folder)

        # Fallback: scan directories for anything chapter-shaped
        for manga_dir in manga_dirs:
            for f in manga_dir.iterdir():
                if f.is_file() and any(
                    f"chapter {label.lower()}" in f.stem.lower() for label in labels
                ):
                    return _extract_images_from_file(f)
                if f.is_dir() and any(label in f.name for label in labels):
                    return _extract_images_from_folder(f)

        return []

    def _navigate_chapter(self, chapter):
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
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
            if idx < len(downloaded) - 1:
                self._navigate_chapter(downloaded[idx + 1])
        except ValueError:
            pass

    def _go_prev_chapter(self):
        if not self._manga:
            return
        title = self._manga.get("title", "")
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
            if idx > 0:
                self._navigate_chapter(downloaded[idx - 1])
        except ValueError:
            pass
