"""
Search page - Search across multiple manga sources.
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QWidget,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T
from ..components.search_result import SearchResultRow
from ..components.toast import Toast


def _compute_search_sources(app) -> list[str]:
    """Build the source list for the search worker.

    Library sources are always included (they're proven-usable for this
    user). Everything else from the supported set is included unless the
    user disabled it on the Sources page (`config["sources.disabled"]`).
    """
    from ...downloader import get_supported_sources

    disabled = set(app.config.get("sources.disabled", []) or [])
    library: set[str] = set()
    for m in app.config.get("manga", []):
        for s in m.get("sources", []) or []:
            d = s.get("source", "")
            if d:
                library.add(d)
        d = m.get("source", "")
        if d:
            library.add(d)

    try:
        supported = set(get_supported_sources())
    except Exception:
        supported = set()

    return sorted(library | (supported - disabled))


class SearchPage(BasePage):
    """Multi-source manga search."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._results = []
        self._result_widgets = []
        self._build()

        self.app.events.subscribe("search_result", self._on_result)
        self.app.events.subscribe("search_complete", self._on_complete)
        self.app.events.subscribe("search_started", self._on_started)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_SM)
        layout.setSpacing(T.PAD_SM)

        # Header
        title = QLabel("Search")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        layout.addWidget(title)
        layout.addSpacing(T.PAD_SM)

        # Search bar
        bar = QHBoxLayout()
        bar.setSpacing(T.PAD_SM)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Search for manga...")
        self._search_entry.setFixedHeight(40)
        self._search_entry.returnPressed.connect(self._do_search)
        bar.addWidget(self._search_entry, 1)

        self._search_btn = QPushButton("Search")
        self._search_btn.setProperty("class", "accent")
        self._search_btn.setFixedHeight(40)
        self._search_btn.setFixedWidth(100)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.clicked.connect(self._do_search)
        bar.addWidget(self._search_btn)

        layout.addLayout(bar)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
        layout.addWidget(self._status_label)

        # Results area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._results_layout = QVBoxLayout(self._scroll_content)
        self._results_layout.setSpacing(2)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

    def _do_search(self):
        query = self._search_entry.text().strip()
        if not query:
            return

        # Clear old results
        for w in self._result_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._result_widgets.clear()
        self._results.clear()

        sources = _compute_search_sources(self.app)
        if not sources:
            self._status_label.setText(
                "No sources enabled — enable some on the Sources tab."
            )
            return
        self._status_label.setText(f"Searching {len(sources)} source(s)…")
        self.app.worker.search_manga(query, sources)

    def _on_started(self, data):
        self._status_label.setText(f"Searching for '{data['query']}'...")
        self._search_btn.setEnabled(False)

    def _on_result(self, data):
        self._results.append(data)
        row = SearchResultRow(self._scroll_content, result=data, on_add=self._add_result)
        self._results_layout.addWidget(row)
        self._result_widgets.append(row)
        self._status_label.setText(f"{len(self._results)} results found...")

    def _on_complete(self, data):
        self._search_btn.setEnabled(True)
        count = len(self._results)
        if count == 0:
            self._status_label.setText("No results found. Try a different query or source.")
        else:
            self._status_label.setText(f"{count} results found")

    def _add_result(self, result):
        """Open Add Manga dialog with prefilled data from search result."""
        from .add_manga import AddMangaDialog
        dialog = AddMangaDialog(self, self.app, prefill={
            "title": result.get("title", ""),
            "url": result.get("url", ""),
        })
        dialog.exec()
