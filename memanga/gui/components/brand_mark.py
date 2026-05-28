"""
Brand mark — small painted "M" + ink-dot logo, theme-aware.

Mirrors svg_assets.brand_mark in memanga-pyside6-spec.json.
Pure QPainter — no SVG asset on disk so it adapts to theme switches
without re-loading anything.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPen, QPainterPath
from PySide6.QtWidgets import QWidget
from .. import theme as T


class BrandMark(QWidget):
    """Custom-painted brand mark. Set ``size`` to 18 (sidebar header)
    or 34 (settings/about). Repaints automatically on theme change.
    """

    def __init__(self, parent=None, size: int = 34):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

        # Repaint when theme switches so the gradient picks up the new
        # accent colors.
        T.on_theme_change(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Scale factor: spec is at 36px; we rescale.
        s = self._size / 36.0
        radius = 9 * s

        # Pull theme colors fresh on every paint.
        toks = T.tokens()
        accent = QColor(toks["accent.primary"])
        accent_2 = QColor(toks["accent.primary_2"])
        on_accent = QColor(toks["accent.on_primary"])

        # Rounded rect with vertical gradient
        rect = QRectF(0, 0, self._size, self._size)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, accent)
        grad.setColorAt(1.0, accent_2)
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        # M strokes
        pen = QPen(on_accent)
        pen.setWidthF(2.9 * s)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)

        path = QPainterPath()
        path.moveTo(9.5 * s, 27 * s)
        path.lineTo(9.5 * s, 9.5 * s)
        path.lineTo(15 * s, 19 * s)
        path.lineTo(21 * s, 9.5 * s)
        path.lineTo(21 * s, 27 * s)
        p.drawPath(path)

        # Small variant skips the second stroke + ink dot for clarity.
        if self._size >= 28:
            # Second descender
            descender = QPainterPath()
            descender.moveTo(21 * s, 27 * s)
            descender.lineTo(21 * s, 14.5 * s)
            p.drawPath(descender)

            # Ink dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(on_accent)
            p.drawEllipse(QPointF(26.5 * s, 24.5 * s), 2.4 * s, 2.4 * s)

        p.end()
