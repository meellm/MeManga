"""
Floating toast notification.
"""

from PySide6.QtWidgets import QLabel, QWidget, QGraphicsOpacityEffect
from PySide6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve
from .. import theme as T

_COLORS = {"info": T.ACCENT, "success": T.SUCCESS, "warning": T.WARNING, "error": T.ERROR}


class Toast(QLabel):
    """Auto-dismissing toast shown at top-right of parent."""

    def __init__(self, parent: QWidget, message: str, kind: str = "info", duration: int = 3000):
        super().__init__(message, parent)
        bg = _COLORS.get(kind, T.ACCENT)
        self.setStyleSheet(
            f"background: {bg}; color: #ffffff; border-radius: 6px; padding: 8px 16px;"
            f" font-size: {T.FONT_SIZE_SM}pt;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

        # Position top-right
        pw = parent.width() if parent else 400
        self.move(pw - self.width() - T.PAD_LG, T.PAD_LG)
        self.raise_()
        self.show()

        QTimer.singleShot(duration, self._dismiss)

    def _dismiss(self):
        try:
            self.deleteLater()
        except Exception:
            pass
