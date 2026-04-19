"""
Sources page — manage which scrapers participate in search.

Two sections:
  - Active: sources used by manga in the user's library (read-only, with a
    health dot from `state.get_all_source_health`).
  - All Supported: every registered scraper, each row a checkbox the user
    can toggle to include/exclude from the Search page's source set.

We persist the *disabled* set (config["sources.disabled"]: list[str]) so the
default — for fresh configs and any newly-added scrapers — is always "all
enabled."
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QCheckBox, QLineEdit,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T


class SourcesPage(BasePage):
    """Dedicated page for managing search-eligible sources."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._all_sources: list[str] = []
        self._supported_widgets: list = []
        self._active_widgets: list = []
        self._build()

    def on_show(self, **kwargs):
        self._refresh()

    # ── Layout ──────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_SM)
        layout.setSpacing(T.PAD_SM)

        title = QLabel("Sources")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        layout.addWidget(title)

        sub = QLabel("Toggle which sources Search should query.")
        sub.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        layout.addWidget(sub)

        # Single scroll area holds both sections so they share a scrollbar.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        self._content_layout = QVBoxLayout(scroll_content)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._content_layout.setSpacing(T.PAD_SM)
        self._scroll.setWidget(scroll_content)
        layout.addWidget(self._scroll, 1)

        # ── Active section ──
        active_lbl = QLabel("Active sources")
        active_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        self._content_layout.addWidget(active_lbl)

        active_sub = QLabel("Used by manga in your library — always included in search.")
        active_sub.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        self._content_layout.addWidget(active_sub)

        self._active_container = QWidget()
        self._active_layout = QVBoxLayout(self._active_container)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(2)
        self._content_layout.addWidget(self._active_container)

        self._content_layout.addSpacing(T.PAD_LG)

        # ── All supported section ──
        supported_lbl = QLabel("All supported sources")
        supported_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        self._content_layout.addWidget(supported_lbl)

        filter_row = QHBoxLayout()
        self._filter_entry = QLineEdit()
        self._filter_entry.setPlaceholderText("Filter…")
        self._filter_entry.setFixedHeight(28)
        self._filter_entry.setFixedWidth(220)
        self._filter_entry.textChanged.connect(self._render_supported)
        filter_row.addWidget(self._filter_entry)
        filter_row.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        filter_row.addWidget(self._count_lbl)
        self._content_layout.addLayout(filter_row)

        self._supported_container = QWidget()
        self._supported_layout = QVBoxLayout(self._supported_container)
        self._supported_layout.setContentsMargins(0, 0, 0, 0)
        self._supported_layout.setSpacing(1)
        self._content_layout.addWidget(self._supported_container)

    # ── Rendering ───────────────────────────────────────────────────────

    def _refresh(self):
        # Lazy-load the supported list once per session.
        if not self._all_sources:
            try:
                from ...downloader import get_supported_sources
                self._all_sources = sorted(get_supported_sources())
            except Exception:
                self._all_sources = []
        self._render_active()
        self._render_supported()

    def _render_active(self):
        for w in self._active_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._active_widgets.clear()

        manga_list = self.app.config.get("manga", [])
        source_manga: dict[str, list] = {}
        for m in manga_list:
            t = m.get("title", "")
            srcs = m.get("sources", []) or []
            if srcs:
                for s in srcs:
                    d = s.get("source", "")
                    if d:
                        source_manga.setdefault(d, []).append(t)
            else:
                d = m.get("source", "")
                if d:
                    source_manga.setdefault(d, []).append(t)

        if not source_manga:
            empty = QLabel("No active sources yet — add a manga to get started.")
            empty.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
            self._active_layout.addWidget(empty)
            self._active_widgets.append(empty)
            return

        all_health = self.app.app_state.get_all_source_health()
        color_map = {
            "ok": T.SUCCESS, "warning": T.WARNING, "error": T.ERROR,
        }
        for domain, titles in sorted(source_manga.items()):
            health = all_health.get(domain, {})
            dot_color = color_map.get(health.get("status", "unknown"), T.FG_MUTED)

            row = QFrame()
            row.setProperty("class", "card")
            row.setFixedHeight(32)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)

            dot = QLabel("\u2022")
            dot.setStyleSheet(f"font-size: {T.FONT_SIZE_MD}pt; color: {dot_color};")
            dot.setFixedWidth(20)
            row_layout.addWidget(dot)

            name = QLabel(domain)
            name.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
            row_layout.addWidget(name, 1)

            count = QLabel(f"{len(titles)} manga")
            count.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            row_layout.addWidget(count)

            self._active_layout.addWidget(row)
            self._active_widgets.append(row)

    def _render_supported(self):
        for w in self._supported_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._supported_widgets.clear()

        query = self._filter_entry.text().strip().lower() if self._filter_entry else ""
        filtered = [s for s in self._all_sources if not query or query in s.lower()]
        self._count_lbl.setText(f"{len(filtered)} of {len(self._all_sources)}")

        disabled = set(self.app.config.get("sources.disabled", []) or [])

        # Count manga per source (for the trailing "N manga" label).
        per_source: dict[str, int] = {}
        for m in self.app.config.get("manga", []):
            for s in m.get("sources", []) or []:
                d = s.get("source", "")
                if d:
                    per_source[d] = per_source.get(d, 0) + 1
            d = m.get("source", "")
            if d:
                per_source[d] = per_source.get(d, 0) + 1

        for source in filtered:
            row = QFrame()
            row.setProperty("class", "card")
            row.setFixedHeight(34)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)

            check = QCheckBox()
            check.setChecked(source not in disabled)
            check.stateChanged.connect(
                lambda state, s=source: self._on_toggle(s, state)
            )
            row_layout.addWidget(check)

            name = QLabel(source)
            name.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
            row_layout.addWidget(name, 1)

            n = per_source.get(source, 0)
            if n:
                used = QLabel(f"{n} in library")
                used.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
                row_layout.addWidget(used)

            self._supported_layout.addWidget(row)
            self._supported_widgets.append(row)

    # ── Toggle handler ──────────────────────────────────────────────────

    def _on_toggle(self, source: str, state):
        from PySide6.QtCore import Qt
        is_checked = state == Qt.CheckState.Checked.value
        disabled = set(self.app.config.get("sources.disabled", []) or [])
        if is_checked:
            disabled.discard(source)
        else:
            disabled.add(source)
        self.app.config.set("sources.disabled", sorted(disabled))
        self.app.config.save()
