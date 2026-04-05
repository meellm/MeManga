"""
Search result row widget.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from .. import theme as T


class SearchResultRow(QFrame):
    """A single search result entry."""

    def __init__(self, parent, result: dict, on_add=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.PAD_MD, T.PAD_SM, T.PAD_MD, T.PAD_SM)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(result.get("title", "Unknown"))
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        info.addWidget(title)

        source = result.get("source", "")
        url = result.get("url", "")[:50]
        sub = QLabel(f"{source}  -  {url}")
        sub.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        info.addWidget(sub)

        layout.addLayout(info, 1)

        if on_add:
            btn = QPushButton("+ Add")
            btn.setProperty("class", "accent")
            btn.setFixedSize(65, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: on_add(result))
            layout.addWidget(btn)
