"""
Base page class for all GUI pages.

Every page paints `bg_0` (the main-area background) so the QStackedWidget
doesn't show Fusion's default light beige between widgets. The background
is repainted on theme switch via a `theme.on_theme_change` subscription.
"""

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget
from .. import theme as T


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

    def on_show(self, **kwargs):
        pass

    def on_hide(self):
        pass
