"""
Brand mark — the app artwork on a small rounded tile.

Draws the same bundled icon set as the window icon, so the sidebar and
the operating system show one logo.
"""

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath
from PySide6.QtWidgets import QWidget
from .. import theme as T


class BrandMark(QWidget):
    """Rounded tile showing the app artwork. Set ``size`` to 18 (sidebar
    header) or 34 (settings/about). Without the icon files it paints a
    plain accent tile, which follows theme changes.
    """

    def __init__(self, parent=None, size: int = 34):
        super().__init__(parent)
        from .. import _load_app_icon
        self._size = size
        self._icon = _load_app_icon()
        self.setFixedSize(size, size)

        # Repaint when theme switches so the fallback tile picks up the
        # new accent colors.
        T.on_theme_change(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        # Scale factor: spec is at 36px; we rescale.
        s = self._size / 36.0
        radius = 9 * s
        rect = QRectF(0, 0, self._size, self._size)

        if self._icon is not None:
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            p.setClipPath(clip)
            # Ask for physical pixels so the art stays sharp on HiDPI.
            pixmap = self._icon.pixmap(
                QSize(self._size, self._size), self.devicePixelRatioF()
            )
            p.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
            p.end()
            return

        # Pull theme colors fresh on every paint.
        toks = T.tokens()
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(toks["accent.primary"]))
        grad.setColorAt(1.0, QColor(toks["accent.primary_2"]))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)
        p.end()
