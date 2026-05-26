"""
Status dropdown — QToolButton + QMenu with colored status dots.

Per memanga-pyside6-spec.json behaviors.dropdowns:
    "Status and Mode dropdowns are NOT QComboBox — use a custom QToolButton
     with arrow_type=NoArrow + a QMenu populated with custom QAction
     widgets (so we can render the colored status dot left of the label)."

Reading=accent, On hold=warn, Completed=lilac, Dropped=danger, Plan=info.
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QAction, QPainter, QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (
    QToolButton, QMenu, QWidget, QHBoxLayout, QLabel, QSizePolicy,
)

from .. import theme as T
from ..theme.tokens import STATUS_TOKEN


# Display label -> internal key (kept in same case as State expects)
STATUS_OPTIONS = [
    ("reading",   "Reading"),
    ("plan",      "Plan to read"),
    ("on-hold",   "On hold"),
    ("completed", "Completed"),
    ("dropped",   "Dropped"),
]


class StatusDropdown(QToolButton):
    """QToolButton that opens a menu of status options with colored dots."""

    value_changed = Signal(str)  # emits the internal status key

    def __init__(self, parent=None, initial: str = "reading"):
        super().__init__(parent)
        self._value = initial
        self.setArrowType(Qt.ArrowType.NoArrow)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Matches CSS `.dropdown .dd-trigger`:
        #   padding: 7px 10px 7px 12px; font-size: 13px (~10pt);
        #   min-width: 140px; border-radius: var(--r-sm) (6px)
        # Right padding = 28px so the hand-painted caret has room without
        # overlapping the value text. The ::menu-indicator rule strips
        # Qt's built-in dropdown arrow that would otherwise stack on top
        # of our caret on macOS.
        self.setStyleSheet(
            f"QToolButton {{"
            f"  background-color: {T.tokens()['surfaces.bg_1']};"
            f"  color: {T.tokens()['text.t_1']};"
            f"  border: 1px solid {T.tokens()['surfaces.border']};"
            f"  border-radius: 6px;"
            f"  padding: 7px 28px 7px 12px;"
            f"  text-align: left;"
            f"  min-width: 140px;"
            f"  font-size: 10pt;"
            f"}}"
            f"QToolButton:hover {{"
            f"  border-color: {T.tokens()['surfaces.border_strong']};"
            f"}}"
            f"QToolButton::menu-indicator {{"
            f"  image: none; width: 0; height: 0;"
            f"  subcontrol-position: right center;"
            f"}}"
        )

        self._menu = QMenu(self)
        self._menu.setStyleSheet(
            f"QMenu {{"
            f"  background-color: {T.tokens()['surfaces.bg_1']};"
            f"  border: 1px solid {T.tokens()['surfaces.border_strong']};"
            f"  border-radius: 6px;"
            f"  padding: 4px;"
            f"}}"
            f"QMenu::item {{"
            f"  padding: 7px 14px 7px 30px;"
            f"  color: {T.tokens()['text.t_1']};"
            f"  border-radius: 4px;"
            f"}}"
            f"QMenu::item:selected {{"
            f"  background-color: {T.tokens()['surfaces.bg_2']};"
            f"}}"
        )
        self.setMenu(self._menu)

        for key, label in STATUS_OPTIONS:
            act = QAction(label, self)
            act.triggered.connect(lambda _, k=key: self._set_value(k))
            self._menu.addAction(act)

        self._refresh_text()
        T.on_theme_change(self._refresh_text)

    # ── value API ──

    def value(self) -> str:
        return self._value

    def set_value(self, key: str):
        self._set_value(key, emit=False)

    def _set_value(self, key: str, emit: bool = True):
        if key == self._value and emit:
            return
        self._value = key
        self._refresh_text()
        if emit:
            self.value_changed.emit(key)

    def _refresh_text(self):
        # Render the dot + label as the button text (QToolButton draws text
        # natively; we paint the dot in paintEvent so it tracks the theme).
        label = next((lbl for k, lbl in STATUS_OPTIONS if k == self._value),
                     self._value.title())
        # Indent the text so the dot has room.
        self.setText("   " + label)
        self.update()

    # ── Paint the leading status dot + the right-side caret ──

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Dot — 7×7 to match CSS `.dropdown .dd-trigger .val .dot`.
            from ..theme.tokens import STATUS_TOKEN
            dot_token = STATUS_TOKEN.get(self._value, "accent.primary")
            dot_color = QColor(T.tokens()[dot_token])
            p.setBrush(dot_color)
            p.setPen(Qt.PenStyle.NoPen)
            d = 7
            cx = 16
            cy = self.height() // 2
            p.drawEllipse(cx - d // 2, cy - d // 2, d, d)

            # Caret — 8×8 chevron (right+bottom borders rotated 45deg).
            cr_col = QColor(T.tokens()["text.t_3"])
            pen = QPen(cr_col)
            pen.setWidthF(1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            ax = self.width() - 18
            ay = self.height() // 2 - 2
            p.drawLine(ax, ay, ax + 4, ay + 4)
            p.drawLine(ax + 4, ay + 4, ax + 8, ay)
        finally:
            # Always end() — otherwise an exception leaves the QPainter
            # active and Qt floods the log with QBackingStore::endPaint
            # warnings.
            p.end()
