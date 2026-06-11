"""
JumpSlider: QSlider that jumps to the absolute clicked position.

A stock QSlider treats a click on the groove as a *page step*
(default 10). On short ranges like 1..8 a single page step saturates
at the minimum or maximum, so clicking only produces the
extremes. This subclass moves the handle to the clicked position
instead, then hands the event to QSlider so dragging keeps working.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class JumpSlider(QSlider):
    """QSlider whose groove clicks set the value at the click point."""

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        # Keep keyboard PageUp/PageDown sane on short ranges too.
        self.setPageStep(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            style = self.style()
            handle = style.subControlRect(
                QStyle.ComplexControl.CC_Slider, opt,
                QStyle.SubControl.SC_SliderHandle, self,
            )
            pos = event.position().toPoint()
            if not handle.contains(pos):
                groove = style.subControlRect(
                    QStyle.ComplexControl.CC_Slider, opt,
                    QStyle.SubControl.SC_SliderGroove, self,
                )
                if self.orientation() == Qt.Orientation.Horizontal:
                    offset = pos.x() - groove.x() - handle.width() // 2
                    span = groove.width() - handle.width()
                else:
                    offset = pos.y() - groove.y() - handle.height() // 2
                    span = groove.height() - handle.height()
                self.setValue(
                    QStyle.sliderValueFromPosition(
                        self.minimum(), self.maximum(),
                        offset, max(1, span), opt.upsideDown,
                    )
                )
                # The handle is now under the cursor, so the default
                # handler below starts a drag instead of a page step.
        super().mousePressEvent(event)
