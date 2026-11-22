"""
Continue-reading mini-card for the Library rail.

Per memanga-pyside6-spec.json spec.screens.library.section_continue_reading:
- 48×68 mini-cover on the left
- Title + sub line + 3px progress bar on the right
- Hover translate-y -1px
- Whole card clickable → openReader(manga, current_chapter)
"""

from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

from .. import theme as T
from .keyboard import is_activation


class ContinueCard(QFrame):
    """Horizontal-layout mini card for the Continue Reading rail."""

    def __init__(self, parent, manga: dict, cover_pixmap: QPixmap, last_chapter: str,
                 progress_pct: float, on_click=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setFixedHeight(96)
        self.setMinimumWidth(240)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Reachable with Tab, opened with Enter/Space (issue #396).
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._manga = manga
        self._on_click = on_click
        self._hover_offset = 0
        # Whole-card click target: name it for screen readers (issue #394).
        self.setAccessibleName(manga.get("title", "Unknown"))
        self.setAccessibleDescription(
            f"Continue reading, last read chapter {last_chapter or 'unknown'}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Mini cover (48×68) ──
        cover = QLabel()
        cover.setFixedSize(48, 68)
        self._cover = cover
        # The cover cache hands out the pixmap at this size (and at the
        # screen's pixel density); it is shown as it is.
        self.update_cover(cover_pixmap)
        cover.setStyleSheet(
            f"background-color: {T.tokens()['surfaces.bg_2']};"
            f"border-radius: 4px;"
        )
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignVCenter)

        # ── Info column ──
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(4)

        title = QLabel(manga.get("title", "Unknown"))
        # Titles come from source sites; show them literally.
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 12pt; font-weight: 600;"
        )
        title.setWordWrap(True)
        # Bumped from 36 → 44 so descenders ('g', 'y', 'p') on the
        # second line aren't clipped at the bottom (issue: bottom of 'g'
        # was getting cropped on cards like "Chainsaw Man Chapter 5").
        title.setMaximumHeight(44)
        info.addWidget(title)

        sub = QLabel(f"Last read: Ch. {last_chapter or '—'}")
        sub.setProperty("role", "mono_meta")
        sub.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 10pt;"
            f"font-family: 'Geist Mono', monospace;"
        )
        info.addWidget(sub)

        info.addStretch(1)

        # 3px progress bar at the very bottom
        from PySide6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(max(0, min(100, int(progress_pct))))
        bar.setTextVisible(False)
        bar.setFixedHeight(3)
        bar.setAccessibleName("Reading progress")
        info.addWidget(bar)

        layout.addLayout(info, 1)

        # Hover animation
        self._anim = QPropertyAnimation(self, b"_offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def update_cover(self, cover_pixmap: QPixmap):
        """Show the cover, also one that finished loading later."""
        if cover_pixmap and not cover_pixmap.isNull():
            self._cover.setPixmap(cover_pixmap)

    # ── Hover translate ──
    def get_offset(self): return self._hover_offset
    def set_offset(self, v):
        self._hover_offset = v
        if hasattr(self, "_initial_y"):
            self.move(self.pos().x(), self._initial_y + v)
    _offset = Property(int, get_offset, set_offset)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not hasattr(self, "_initial_y"):
            self._initial_y = self.pos().y()

    def enterEvent(self, ev):
        if hasattr(self, "_initial_y"):
            self._anim.stop()
            self._anim.setStartValue(self._hover_offset)
            self._anim.setEndValue(-1)
            self._anim.start()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if hasattr(self, "_initial_y"):
            self._anim.stop()
            self._anim.setStartValue(self._hover_offset)
            self._anim.setEndValue(0)
            self._anim.start()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._manga)

    def keyPressEvent(self, ev):
        if is_activation(ev) and self._on_click:
            self._on_click(self._manga)
        else:
            super().keyPressEvent(ev)
