"""
FlowFrame: a row of widgets that wraps onto more lines when it is narrow.

The layout follows Qt's Flow Layout example. The frame reports the height
its lines need at its current width, as WrappingLabel does for text: the
page layouts are top-aligned, which sizes them from sizeHint() and ignores
heightForWidth().
"""

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QLayout


class FlowLayout(QLayout):
    """Lays its items out left to right and starts a new line when the
    next one does not fit. Items keep their size hint (never more than
    the line width), and each line is centred vertically.

    With ``last_right`` the last item sits at the right edge of its line,
    like the trailing group of a row that ends in a stretch.
    """

    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6,
                 last_right: bool = False):
        super().__init__(parent)
        # No style margins: callers set the ones they want.
        self.setContentsMargins(0, 0, 0, 0)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._last_right = last_right

    # ── QLayout interface ──

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        """Everything on one line."""
        items = self._visible()
        width = sum(i.sizeHint().width() for i in items)
        width += self._h_spacing * max(0, len(items) - 1)
        height = max((i.sizeHint().height() for i in items), default=0)
        return self._with_margins(QSize(width, height))

    def minimumSize(self):
        """As narrow as the widest item: one item per line."""
        items = self._visible()
        width = max((i.minimumSize().width() for i in items), default=0)
        height = max((i.minimumSize().height() for i in items), default=0)
        return self._with_margins(QSize(width, height))

    # ── Layout ──

    def _visible(self):
        return [item for item in self._items if not item.isEmpty()]

    def _with_margins(self, size: QSize) -> QSize:
        m = self.contentsMargins()
        return QSize(size.width() + m.left() + m.right(),
                     size.height() + m.top() + m.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Place the items in ``rect`` (when ``apply``); return the
        height they need."""
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        line_width = max(1, area.width())

        lines, line, x = [], [], 0
        for item in self._visible():
            hint = item.sizeHint()
            size = QSize(min(hint.width(), line_width), hint.height())
            if line and x + size.width() > line_width:
                lines.append(line)
                line, x = [], 0
            line.append((item, size, x))
            x += size.width() + self._h_spacing
        if line:
            lines.append(line)

        y = area.y()
        for n, line in enumerate(lines):
            height = max(size.height() for _item, size, _x in line)
            if apply:
                for i, (item, size, x) in enumerate(line):
                    left = area.x() + x
                    if (self._last_right and n == len(lines) - 1
                            and i == len(line) - 1):
                        left = max(left, area.x() + line_width - size.width())
                    top = y + (height - size.height()) // 2
                    item.setGeometry(QRect(QPoint(left, top), size))
            y += height + (self._v_spacing if n < len(lines) - 1 else 0)
        return y - area.y() + m.top() + m.bottom()


class FlowFrame(QFrame):
    """A frame holding a FlowLayout. It can be styled like any frame
    (``role`` property) and asks its parent layout for the height its
    lines take at its current width."""

    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6,
                 last_right: bool = False):
        super().__init__(parent)
        self._flow = FlowLayout(self, h_spacing, v_spacing, last_right)
        self._fitted_height = 0

    def flow(self) -> FlowLayout:
        return self._flow

    def addWidget(self, widget):
        self._flow.addWidget(widget)

    def _fit_height(self):
        height = self.heightForWidth(self.width())
        if height > 0 and height != self._fitted_height:
            self._fitted_height = height
            self.updateGeometry()

    def _with_fitted_height(self, size: QSize) -> QSize:
        if self._fitted_height > 0:
            size.setHeight(self._fitted_height)
        return size

    def sizeHint(self):
        return self._with_fitted_height(super().sizeHint())

    def minimumSizeHint(self):
        return self._with_fitted_height(super().minimumSizeHint())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def event(self, event):
        handled = super().event(event)
        # An item changed size (new text, style) while the width stayed.
        if event.type() == QEvent.Type.LayoutRequest:
            self._fit_height()
        return handled
