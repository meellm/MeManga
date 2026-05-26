"""
Search result row widget.

One per manga hit from `search_manga`. Shows the title, source domain,
and a prominent "+ Add" button on the right that opens the Add Manga
dialog prefilled from the result.
"""

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt

from .. import theme as T


class SearchResultRow(QFrame):
    """A single search result entry — title + source on the left,
    accent-coloured Add button pinned to the right.
    """

    def __init__(self, parent, result: dict, on_add=None):
        super().__init__(parent)
        self._result = result
        self._on_add = on_add

        # Card surface so the row reads as its own clickable unit.
        self.setProperty("role", "card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Was 52 — too tight; the Add button ended up clipped by the
        # row's own fixed height on Windows. 64 gives the button +
        # 2-line label + padding clean breathing room.
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Left: title (bold) + source · url (mono small)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 0, 0, 0)
        title = QLabel(result.get("title", "Unknown"))
        title.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 11pt;"
            f"font-weight: 600;"
        )
        title.setWordWrap(False)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        info.addWidget(title)

        source = result.get("source", "")
        url = (result.get("url", "") or "")[:60]
        sub = QLabel(f"{source}  ·  {url}")
        sub.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 9pt;"
            f"font-family: 'Geist Mono', monospace;"
        )
        info.addWidget(sub)
        layout.addLayout(info, 1)

        # Right: prominent Add button. setVisible(True) explicitly +
        # min size so it can't be clipped to 0 px when the row width
        # is tight.
        if on_add:
            btn = QPushButton("+ Add")
            btn.setProperty("variant", "primary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumSize(78, 32)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed,
                               QSizePolicy.Policy.Fixed)
            btn.clicked.connect(self._handle_add)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._add_btn = btn

        # Re-paint with theme tokens when theme switches.
        T.on_theme_change(self._restyle)
        self._restyle()

    def _handle_add(self):
        if callable(self._on_add):
            self._on_add(self._result)

    def _restyle(self):
        toks = T.tokens()
        bg = toks.get("surfaces.bg_1", "#1A1A1A")
        border = toks.get("surfaces.border", "rgba(255,255,255,0.06)")
        self.setStyleSheet(
            f"SearchResultRow {{"
            f"  background-color: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
        )
