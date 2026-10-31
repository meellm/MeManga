"""
Reader input: keyboard shortcuts, zoom, click-and-drag pan and touchpad
pinch for ReaderPage.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent


class ReaderInputMixin:
    """Keyboard, wheel, mouse and gesture handling for ReaderPage.

    Must precede the QWidget base so these Qt event handlers override
    it. ReaderPage initialises the state used here (zoom, pan and pinch
    fields, ``_scroll``) and provides the page, layout and chapter
    navigation methods the shortcuts call."""

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

    def _zoom_in(self):
        if self._zoom_level < self.ZOOM_MAX:
            self._zoom_level += self.ZOOM_STEP
            self._rebuild_images()

    def _zoom_out(self):
        if self._zoom_level > self.ZOOM_MIN:
            self._zoom_level -= self.ZOOM_STEP
            self._rebuild_images()

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
