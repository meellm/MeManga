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
        from PySide6.QtWidgets import QFrame
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        header_w = QWidget()
        h_layout = QVBoxLayout(header_w)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Search")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)
        h_layout.addLayout(top_row)

        meta = QLabel("Searching across enabled sources")
        meta.setProperty("role", "meta")
        h_layout.addWidget(meta)
        root.addWidget(header_w)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # Body wrapper
        body_w = QWidget()
        layout = QVBoxLayout(body_w)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.setSpacing(T.PAD_SM)
        root.addWidget(body_w, 1)

        # ── Hero card with search input (matches HTML spec.screens.search.hero)
        hero = QFrame()
        hero.setProperty("role", "card")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 22, 22, 22)
        hero_l.setSpacing(14)

        # Inner search bar: bg_0 container, leading magnifier icon, ⌘K kbd hint,
        # accent Search button on the right.
        bar_wrap = QFrame()
        bar_wrap.setProperty("role", "card_2")
        bar = QHBoxLayout(bar_wrap)
        bar.setContentsMargins(16, 4, 4, 4)
        bar.setSpacing(8)

        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        mag_lbl = QLabel()
        mag_lbl.setPixmap(_ic("search", T.tokens()["text.t_3"], 18).pixmap(QSize(18, 18)))
        bar.addWidget(mag_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Search for manga across enabled sources…")
        self._search_entry.setFixedHeight(40)
        self._search_entry.setStyleSheet("border: none; background: transparent; font-size: 13pt;")
        self._search_entry.returnPressed.connect(self._do_search)
        bar.addWidget(self._search_entry, 1)

        # ⌘K kbd hint chip
        kbd = QLabel("⌘K")
        kbd.setProperty("role", "mono_meta")
        kbd.setStyleSheet(
            f"background: {T.tokens()['surfaces.bg_3']}; color: {T.tokens()['text.t_3']};"
            f"padding: 3px 8px; border-radius: 4px;"
        )
        bar.addWidget(kbd, 0, Qt.AlignmentFlag.AlignVCenter)

        self._search_btn = QPushButton("Search")
        self._search_btn.setProperty("variant", "primary")
        self._search_btn.setFixedHeight(34)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.clicked.connect(self._do_search)
        bar.addWidget(self._search_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        hero_l.addWidget(bar_wrap)

        # Status / hint under the input
        self._status_label = QLabel("Type a title and press Enter to search.")
        self._status_label.setProperty("role", "hint")
        hero_l.addWidget(self._status_label)

        # Recent searches chip row (persisted across launches).
        recents_wrap = QWidget()
        rec_l = QHBoxLayout(recents_wrap)
        rec_l.setContentsMargins(0, 6, 0, 0)
        rec_l.setSpacing(6)
        rec_lbl = QLabel("Recent:")
        rec_lbl.setProperty("role", "hint")
        rec_l.addWidget(rec_lbl)
        self._recent_row = rec_l  # so _refresh_recents can append/clear
        self._recents_wrap = recents_wrap
        rec_l.addStretch(1)
        hero_l.addWidget(recents_wrap)
        self._refresh_recents()

        layout.addWidget(hero)
        layout.addSpacing(8)

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

    def on_show(self, **kwargs):
        # Refresh recent-search chips when the user navigates back
        # (e.g. after searching twice from elsewhere).
        try:
            self._refresh_recents()
        except Exception:
            pass

    def _do_search(self):
        query = self._search_entry.text().strip()
        if not query:
            return

        # Persist the query for the recent-chip row (deduped + capped at 8).
        try:
            self.app.app_state.add_search_query(query)
            self._refresh_recents()
        except Exception:
            pass

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

    def _refresh_recents(self):
        """Rebuild the recent-search chip row from persisted state."""
        if not hasattr(self, "_recent_row"):
            return
        # Wipe existing chips (keep the "Recent:" label at index 0 and the
        # trailing stretch at the end).
        layout = self._recent_row
        while layout.count() > 2:
            item = layout.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()

        try:
            recents = self.app.app_state.get_recent_searches(limit=8)
        except Exception:
            recents = []

        if not recents:
            self._recents_wrap.setVisible(False)
            return

        self._recents_wrap.setVisible(True)
        from PySide6.QtWidgets import QPushButton as _QPB
        for q in recents:
            chip = _QPB(f"⌘  {q}")
            chip.setProperty("variant", "chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, query=q: self._run_recent(query))
            # Insert just before the trailing stretch (index = count() - 1).
            layout.insertWidget(layout.count() - 1, chip)

    def _run_recent(self, query: str):
        self._search_entry.setText(query)
        self._do_search()

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
