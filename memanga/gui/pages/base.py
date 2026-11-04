"""
Base page class for all GUI pages.

Every page paints `bg_0` (the main-area background) so the QStackedWidget
doesn't show Fusion's default light beige between widgets. The background
is repainted on theme switch via a `theme.on_theme_change` subscription.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QScrollArea, QWidget
from .. import theme as T

_PLAIN = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)


class BasePage(QWidget):
    """Base class for all pages. Subclass and override on_show/on_hide.

    Paints `bg_0` so the page body matches the design (instead of showing
    Fusion's default beige). Repaints on theme switch.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.setAutoFillBackground(True)
        self._apply_bg()
        T.on_theme_change(self._apply_bg)

    def _apply_bg(self):
        bg = T.tokens()["surfaces.bg_0"]
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        self.setPalette(pal)
        self.update()

    def add_shortcut(self, keys, slot) -> QShortcut:
        """A shortcut active only while this page is showing: Qt skips
        shortcuts whose parent is hidden, and the page stack hides every
        page but the current one (issue #396)."""
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.activated.connect(slot)
        return shortcut

    @staticmethod
    def focus_field(entry):
        """Put the cursor in a text field with its text selected, so
        typing replaces it."""
        entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        entry.selectAll()

    # ── Keyboard scrolling (issue #396) ──
    # Page scroll areas are not Tab stops. A control inside one passes
    # Page Up/Down it doesn't use on to the area, which scrolls; from a
    # control outside it (the page header) the keys arrive here instead.

    def _main_scroll_area(self):
        """The largest visible scroll area of the page that can scroll."""
        areas = [a for a in self.findChildren(QScrollArea)
                 if a.isVisible() and a.verticalScrollBar().maximum() > 0]
        return max(areas, key=lambda a: a.width() * a.height(), default=None)

    def keyPressEvent(self, event):
        key = event.key()
        if (key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
                and event.modifiers() in _PLAIN):
            area = self._main_scroll_area()
            if area is not None:
                bar = area.verticalScrollBar()
                step = bar.pageStep()
                bar.setValue(bar.value()
                             + (step if key == Qt.Key.Key_PageDown else -step))
                return
        super().keyPressEvent(event)

    def on_show(self, **kwargs):
        pass

    def on_hide(self):
        pass
