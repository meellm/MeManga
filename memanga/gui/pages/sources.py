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
from PySide6.QtCore import Qt, QTimer
from .base import BasePage
from .. import theme as T


class SourcesPage(BasePage):
    """Dedicated page for managing search-eligible sources."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._all_sources: list[str] = []
        self._supported_widgets: list = []
        self._active_widgets: list = []
        self._filter_pending = False
        self._build()

        # Live-refresh the Active section when manga are added / removed /
        # edited from anywhere in the app — otherwise this page can drift
        # if the user navigates here and then mutates the library elsewhere
        # (e.g. via context menu).
        self.app.events.subscribe(
            "library_updated", lambda d: self._on_library_updated()
        )
        # Repaint when source health pings finish so latency badges update.
        self.app.events.subscribe(
            "sources_health_updated", lambda d: self._on_health_updated()
        )

    def on_show(self, **kwargs):
        self._refresh()

    def _on_recheck_health(self):
        """Kick off background HEAD probes against every enabled source.

        Surfaces an instant toast so the user knows the request was
        accepted; the actual badges update via the
        ``sources_health_updated`` event when the probes finish.
        """
        from ..components.toast import Toast
        if not self._all_sources:
            try:
                from ...downloader import get_supported_sources
                self._all_sources = sorted(get_supported_sources())
            except Exception:
                Toast(self, "No sources to check", kind="warning")
                return

        disabled = set(self.app.config.get("sources.disabled", []) or [])
        active = [s for s in self._all_sources if s not in disabled]
        if not active:
            Toast(self, "No active sources to check", kind="warning")
            return

        Toast(self, f"Checking {len(active)} source(s)…", kind="info")
        self._recheck_btn.setEnabled(False)
        self.app.worker.ping_sources(active, self.app.app_state)

    def _on_health_updated(self):
        self._recheck_btn.setEnabled(True)
        if self.isVisible():
            self._render_active()
            self._render_supported()

    def _on_library_updated(self):
        if self.isVisible():
            self._render_active()

    # ── Layout ──────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_w = QWidget()
        h_layout = QVBoxLayout(header_w)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Sources")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)

        # Re-check health button — issues HEAD probes against every
        # enabled source via worker.ping_sources.
        from ..assets.icons import icon as _ic
        self._recheck_btn = QPushButton("  Re-check health")
        self._recheck_btn.setProperty("variant", "ghost")
        self._recheck_btn.setIcon(_ic("refresh", T.tokens()["text.t_2"], 14))
        self._recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recheck_btn.clicked.connect(self._on_recheck_health)
        top_row.addWidget(self._recheck_btn)
        h_layout.addLayout(top_row)

        sub = QLabel("Toggle which sources Search should query.")
        sub.setProperty("role", "meta")
        h_layout.addWidget(sub)
        root.addWidget(header_w)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        body_w = QWidget()
        layout = QVBoxLayout(body_w)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.setSpacing(T.PAD_SM)
        root.addWidget(body_w, 1)

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
        # Debounce: rebuilding the supported list on every keystroke
        # gets stuttery as the scraper count grows. 150ms is short
        # enough to feel instant, long enough to coalesce typing.
        self._filter_entry.textChanged.connect(self._on_filter_changed)
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

            # Wrap in a styled card frame so each active source gets the
            # accent-tinted border + gradient feel (HTML active card spec).
            wrap = QFrame()
            wrap.setStyleSheet(
                f"QFrame {{"
                f"  background-color: {T.tokens()['surfaces.bg_1']};"
                f"  border: 1px solid {T.tokens()['accent.ring']};"
                f"  border-radius: 8px;"
                f"  padding: 0;"
                f"}}"
            )
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(row)
            self._active_layout.addWidget(wrap)
            self._active_widgets.append(wrap)

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

        # Letter-group the filtered list (matches HTML spec.screens.sources
        # supported_sources.letter_group_head).
        from collections import OrderedDict
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for source in filtered:
            letter = (source[0] if source else "?").upper()
            if not letter.isalpha():
                letter = "#"
            groups.setdefault(letter, []).append(source)

        for letter, sources_in_grp in groups.items():
            # Group header strip
            head = QFrame()
            head.setStyleSheet(
                f"QFrame {{"
                f"  background-color: {T.tokens()['surfaces.bg_2']};"
                f"  border: none;"
                f"}}"
            )
            head.setFixedHeight(28)
            head_l = QHBoxLayout(head)
            head_l.setContentsMargins(16, 0, 16, 0)
            letter_lbl = QLabel(letter)
            letter_lbl.setStyleSheet(
                f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                f"color: {T.tokens()['text.t_3']}; font-weight: 600;"
            )
            head_l.addWidget(letter_lbl)
            head_l.addStretch(1)
            count_lbl = QLabel(str(len(sources_in_grp)))
            count_lbl.setStyleSheet(
                f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                f"color: {T.tokens()['text.t_3']};"
            )
            head_l.addWidget(count_lbl)
            self._supported_layout.addWidget(head)
            self._supported_widgets.append(head)

            for source in sources_in_grp:
                row = QFrame()
                row.setProperty("class", "card")
                row.setFixedHeight(34)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)

                check = QCheckBox()
                check.setChecked(source not in disabled)
                check.stateChanged.connect(
                    lambda _=None, s=source, c=check: self._on_toggle(s, c.isChecked())
                )
                row_layout.addWidget(check)

                name = QLabel(source)
                name.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
                row_layout.addWidget(name, 1)

                # Health latency (if pinged)
                hh = self.app.app_state.get_source_health(source) or {}
                if hh.get("latency_ms") is not None:
                    lat = QLabel(f"{hh['latency_ms']}ms")
                    lat.setStyleSheet(
                        f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                        f"color: {T.tokens()['text.t_3']};"
                    )
                    row_layout.addWidget(lat)

                n = per_source.get(source, 0)
                if n:
                    used = QLabel(f"{n} in library")
                    used.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
                    row_layout.addWidget(used)

                self._supported_layout.addWidget(row)
                self._supported_widgets.append(row)

    # ── Filter debounce ─────────────────────────────────────────────────

    def _on_filter_changed(self, _text=""):
        if self._filter_pending:
            return
        self._filter_pending = True
        QTimer.singleShot(150, self._do_filter)

    def _do_filter(self):
        self._filter_pending = False
        self._render_supported()

    # ── Toggle handler ──────────────────────────────────────────────────

    def _on_toggle(self, source: str, is_checked: bool):
        disabled = set(self.app.config.get("sources.disabled", []) or [])
        if is_checked:
            disabled.discard(source)
        else:
            disabled.add(source)
        self.app.config.set("sources.disabled", sorted(disabled))
        self.app.config.save()
