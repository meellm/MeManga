"""
WrappingLabel: a word-wrapped QLabel that reports the height its text needs.
"""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel


class WrappingLabel(QLabel):
    """A word-wrapped label whose size hints carry the height its text
    needs at its current width. The tab layouts are top-aligned, which
    sizes them from sizeHint() and ignores heightForWidth(), so a long
    wrapped text would otherwise be clipped and overlap the next row.

    The hints are overridden instead of setting a minimum height:
    QLabel.heightForWidth() never returns less than minimumHeight(), so
    the height could then only grow when the label gets wider."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._text_height = 0

    def _fit_height(self) -> None:
        height = self.heightForWidth(self.width())
        if height != self._text_height:
            self._text_height = height
            self.updateGeometry()

    def _with_text_height(self, size):
        if self._text_height > 0:
            size.setHeight(self._text_height)
        return size

    def sizeHint(self):
        return self._with_text_height(super().sizeHint())

    def minimumSizeHint(self):
        return self._with_text_height(super().minimumSizeHint())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        # A style sheet can change the font after the first resize.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_height()

    def setText(self, text):
        super().setText(text)
        # A status line can change its text without changing width.
        self._fit_height()
