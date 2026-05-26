"""
Search result row widget.

One per manga hit from `search_manga`. Shows the title, source domain,
a chapter-count chip (lazy-loaded), and a prominent "+ Add" button on
the right that opens the Add Manga dialog prefilled from the result.

The chapter count is fetched in the background once the row is built
(`set_chapter_count` is called by the search page when the worker's
`search_chapter_count` event arrives). While the lookup is in-flight
the chip stays hidden so we don't show stale or misleading numbers.
"""

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt

from .. import theme as T


class SearchResultRow(QFrame):
    """A single search result entry — title + source on the left,
    chapter-count chip + accent Add button pinned to the right.
    """

    def __init__(self, parent, result: dict, on_add=None):
        super().__init__(parent)
        self._result = result
        self._on_add = on_add

        # Card surface so the row reads as its own clickable unit.
        self.setProperty("role", "card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 64 px gives the Add button + 2-line label + padding clean
        # breathing room (52 was clipping the button on Windows).
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

        # Chapter-count chip — same style language as the source-row
        # language chip in Sources tab (small mono, t_3, no border).
        # Hidden until set_chapter_count() lands a non-zero number;
        # 0 stays hidden so the user can immediately see which sources
        # don't actually have the manga / are out of date.
        self._count_chip = QLabel("")
        self._count_chip.setStyleSheet(
            f"QLabel {{"
            f"  color: {T.tokens()['text.t_3']};"
            f"  font-family: 'Geist Mono', monospace;"
            f"  font-size: 8pt; font-weight: 600;"
            f"  letter-spacing: 0.5px;"
            f"  padding: 0px 6px;"
            f"}}"
        )
        self._count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_chip.hide()
        layout.addWidget(self._count_chip, 0, Qt.AlignmentFlag.AlignVCenter)

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

    # ── public ────────────────────────────────────────────────────

    @property
    def url(self) -> str:
        return self._result.get("url", "")

    @property
    def source(self) -> str:
        return self._result.get("source", "")

    def set_chapter_count(self, count: int):
        """Show "{n} ch" chip when > 0; hide when 0 (so the user can
        immediately see which sources don't actually carry the title).
        Negative count means lookup failed → also hidden.
        """
        if count is None or count <= 0:
            self._count_chip.setText("")
            self._count_chip.hide()
            return
        self._count_chip.setText(f"{count} ch")
        self._count_chip.show()

    def _handle_add(self):
        if callable(self._on_add):
            # Pass the freshest result dict including any chapter count
            # we picked up so AddMangaDialog can show it as context.
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
        # The chip palette tracks t_3, refresh on theme flip.
        self._count_chip.setStyleSheet(
            f"QLabel {{"
            f"  color: {toks.get('text.t_3', '#888')};"
            f"  font-family: 'Geist Mono', monospace;"
            f"  font-size: 8pt; font-weight: 600;"
            f"  letter-spacing: 0.5px;"
            f"  padding: 0px 6px;"
            f"}}"
        )
