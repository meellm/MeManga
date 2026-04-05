"""
Download progress bar widget.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
from PySide6.QtCore import Qt
from .. import theme as T


class ProgressItem(QFrame):
    """A single download progress entry."""

    def __init__(self, parent, task_id: str, title: str, chapter: str, on_cancel=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.task_id = task_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_MD, T.PAD_SM, T.PAD_MD, T.PAD_SM)
        layout.setSpacing(T.PAD_XS)

        top = QHBoxLayout()
        title_label = QLabel(f"{title} - Ch. {chapter}")
        title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        top.addWidget(title_label, 1)

        self._status_label = QLabel("Waiting...")
        self._status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        top.addWidget(self._status_label)

        if on_cancel:
            cancel_btn = QPushButton("x")
            cancel_btn.setFixedSize(22, 22)
            cancel_btn.setStyleSheet(
                f"background: transparent; border: none; color: {T.FG_MUTED}; font-weight: bold;"
            )
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.clicked.connect(lambda: on_cancel(task_id))
            top.addWidget(cancel_btn)

        layout.addLayout(top)

        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

    def update_progress(self, current: int, total: int):
        if total > 0:
            self._progress.setValue(int(current / total * 100))
            self._status_label.setText(f"{current}/{total} pages")

    def set_complete(self, path: str = None):
        self._progress.setValue(100)
        self._status_label.setText("Complete")
        self._status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.SUCCESS};")

    def set_error(self, error: str):
        self._status_label.setText(f"Error: {error[:40]}")
        self._status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
