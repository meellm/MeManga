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
from PySide6.QtGui import QFontMetrics, QPainter

from .. import theme as T


class _ElideLabel(QLabel):
    """QLabel that paints its text with right-elision when there
    isn't enough room.

    Plain QLabel just clips long text or — with wordWrap — expands
    vertically. Neither is right for the search result row: the
    title needs to **shrink** so the chip and Add button on the
    right keep their fixed widths. Custom paint with
    `QFontMetrics.elidedText` is the canonical Qt fix.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        # We don't want the label asking the layout for room for its
        # full text — set its preferred horizontal size to its minimum.
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)
        self.setToolTip(text)

    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        super().setText(text)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        try:
            fm = QFontMetrics(self.font())
            elided = fm.elidedText(
                self._full_text, Qt.TextElideMode.ElideRight,
                self.width(),
            )
            # Honor stylesheet color via palette.
            p.setPen(self.palette().color(self.foregroundRole()))
            p.drawText(self.rect(), int(self.alignment()) | Qt.TextFlag.TextSingleLine, elided)
        finally:
            p.end()


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

        # Left: title (bold, elided) + source · url (mono small, elided).
        # Wrap in a QWidget so the layout can size-constrain the whole
        # info column without the chip/button having to compete.
        info_wrap = QFrame()
        info_wrap.setStyleSheet("background: transparent; border: none;")
        info_wrap.setSizePolicy(QSizePolicy.Policy.Ignored,
                                  QSizePolicy.Policy.Preferred)
        info = QVBoxLayout(info_wrap)
        info.setSpacing(2)
        info.setContentsMargins(0, 0, 0, 0)
        title = _ElideLabel(result.get("title", "Unknown"))
        title.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 11pt;"
            f"font-weight: 600;"
        )
        info.addWidget(title)

        source = result.get("source", "")
        url = result.get("url", "") or ""
        sub = _ElideLabel(f"{source}  ·  {url}")
        sub.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 9pt;"
            f"font-family: 'Geist Mono', monospace;"
        )
        info.addWidget(sub)
        # `1` here means: this column gets all the leftover horizontal
        # space after the chip + Add button claim their fixed widths.
        # Combined with the elide-label inside, long titles truncate
        # with "…" instead of pushing the chip off the row.
        layout.addWidget(info_wrap, 1)
        self._title_lbl = title
        self._sub_lbl = sub

        # Chapter-count chip — same style language as the source-row
        # language chip in Sources tab (small mono, t_3, no border).
        # Hidden until set_chapter_count() lands a non-zero number;
        # 0 stays hidden so the user can immediately see which sources
        # don't actually have the manga / are out of date.
        self._count_chip = QLabel("")
        self._count_chip.setSizePolicy(QSizePolicy.Policy.Fixed,
                                         QSizePolicy.Policy.Fixed)
        self._count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_chip.hide()
        layout.addWidget(self._count_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        # Right: prominent Add button. Fixed size policy + minimum so
        # the layout can't shrink it to 0 px when titles are long.
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
        self._count_chip.adjustSize()

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
