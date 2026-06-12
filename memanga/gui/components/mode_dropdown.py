"""
Mode dropdown — QToolButton + QMenu, matches StatusDropdown shape.

Per memanga-pyside6-spec.json behaviors.dropdowns:
    "Mode dropdown items render two-line (label + description)."

Two-line option rendering is done with a custom QWidgetAction so each
menu item shows a title + small grey description. The button itself
shows just the current label.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QToolButton, QMenu, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QWidgetAction,
)

from .. import theme as T


MODE_OPTIONS = [
    ("auto",   "Auto",   "New chapters download after each check."),
    ("manual", "Manual", "Download chapters individually below."),
]


class _ModeItemWidget(QWidget):
    """Two-line widget shown inside the menu: title + small description."""

    def __init__(self, label: str, desc: str, on_click, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(2)
        title = QLabel(label)
        title.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 12pt; font-weight: 500;"
        )
        layout.addWidget(title)
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 10pt;"
        )
        d.setWordWrap(True)
        layout.addWidget(d)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(ev)

    def enterEvent(self, ev):
        self.setStyleSheet(f"background-color: {T.tokens()['surfaces.bg_2']}; border-radius: 4px;")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.setStyleSheet("")
        super().leaveEvent(ev)


class ModeDropdown(QToolButton):
    """QToolButton with a 2-line option menu (Auto / Manual + descriptions)."""

    value_changed = Signal(str)

    def __init__(self, parent=None, initial: str = "auto", options=None):
        super().__init__(parent)
        # `options` lets subclasses (e.g. LayoutDropdown) reuse the same
        # trigger + two-line menu with a different option set.
        self._options = list(options) if options is not None else MODE_OPTIONS
        self._value = initial
        self.setArrowType(Qt.ArrowType.NoArrow)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Matches CSS `.dropdown .dd-trigger` (same as StatusDropdown).
        # Strips Qt's built-in ::menu-indicator so it doesn't stack on
        # top of our hand-painted caret.
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
        )
        self.setMenu(self._menu)

        for key, label, desc in self._options:
            wa = QWidgetAction(self)
            item = _ModeItemWidget(label, desc, lambda k=key: self._on_pick(k))
            item.setMinimumWidth(260)
            wa.setDefaultWidget(item)
            self._menu.addAction(wa)

        self._refresh_text()
        T.on_theme_change(self._refresh_text)

    def value(self) -> str:
        return self._value

    def set_value(self, key: str):
        if key not in {k for k, _, _ in self._options}:
            return
        self._value = key
        self._refresh_text()

    def _on_pick(self, key: str):
        if key == self._value:
            self._menu.close()
            return
        self._value = key
        self._refresh_text()
        self._menu.close()
        self.value_changed.emit(key)

    def _refresh_text(self):
        label = next((lbl for k, lbl, _ in self._options if k == self._value),
                     self._value.title())
        self.setText(label)
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        # Caret on the right edge — same look as StatusDropdown.
        from PySide6.QtGui import QPen
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(T.tokens()["text.t_3"]))
            pen.setWidthF(1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            ax = self.width() - 18
            ay = self.height() // 2 - 2
            p.drawLine(ax, ay, ax + 4, ay + 4)
            p.drawLine(ax + 4, ay + 4, ax + 8, ay)
        finally:
            p.end()
