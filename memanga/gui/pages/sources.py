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
        # No point pinging individual sources when the box itself is
        # offline — would just light up every source as red and
        # confuse the user.
        net = getattr(self.app, "network", None)
        if net is not None and not net.is_online:
            Toast(self,
                   "You're offline — health checks resume when reconnected.",
                   kind="warn")
            return
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

    def _show_active_more(self, domain: str):
        """Quick-actions menu for an active source card."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QCursor
        from ..components.toast import Toast
        menu = QMenu(self)
        a_recheck = QAction(f"Re-check {domain}", self)
        a_recheck.triggered.connect(
            lambda: self.app.worker.ping_sources([domain], self.app.app_state)
        )
        menu.addAction(a_recheck)
        a_disable = QAction("Disable in search", self)
        a_disable.triggered.connect(lambda: self._on_toggle(domain, False))
        menu.addAction(a_disable)
        menu.exec(QCursor.pos())

    def _on_library_updated(self):
        if self.isVisible():
            self._render_active()
            self._refresh_header_meta()

    # ── Language tag lookup ─────────────────────────────────────────────
    # Backend doesn't expose per-scraper language. Until it does, infer
    # from domain TLD / known clusters: ".es" → ES, japanese-known hosts
    # → JP, everything else defaults to EN. Returned tag must match the
    # chip keys exactly ("EN" / "JP" / "ES" / "OTHER").

    _JP_HOSTS = {"mangago.me", "mangamonk.com", "tortugaceviri.com"}

    @classmethod
    def _lang_of(cls, domain: str) -> str:
        d = domain.lower()
        if d.endswith(".es") or "comics.es" in d:
            return "ES"
        if d in cls._JP_HOSTS or d.endswith(".jp"):
            return "JP"
        return "EN"

    def _set_lang_filter(self, key: str):
        if key == self._lang_filter:
            return
        self._lang_filter = key
        for k, btn in self._lang_chips.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
        self._render_supported()

    def _refresh_header_meta(self):
        """Recompute the multi-part header meta line from live state."""
        if not self._all_sources:
            try:
                from ...downloader import get_supported_sources
                self._all_sources = sorted(get_supported_sources())
            except Exception:
                self._all_sources = []
        total = len(self._all_sources)
        disabled = set(self.app.config.get("sources.disabled", []) or [])
        # Count "active" = enabled AND actually used by a manga in the library.
        used = self._domains_in_library()
        active = [s for s in self._all_sources
                  if s not in disabled and s in used]
        # Per-lang breakdown of those active sources (matches HTML
        # "3 EN, 0 JP, 0 ES selected" semantics).
        en = sum(1 for s in active if self._lang_of(s) == "EN")
        jp = sum(1 for s in active if self._lang_of(s) == "JP")
        es = sum(1 for s in active if self._lang_of(s) == "ES")
        self._meta_label.setText(
            f"{len(active)} active  ·  {total} available  "
            f"·  {en} EN, {jp} JP, {es} ES selected"
        )

    def _domains_in_library(self) -> set[str]:
        out: set[str] = set()
        for m in self.app.config.get("manga", []) or []:
            for s in m.get("sources", []) or []:
                d = s.get("source", "")
                if d:
                    out.add(d)
            d = m.get("source", "")
            if d:
                out.add(d)
        return out

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

        # Multi-part meta line matching HTML spec.screens.sources.header:
        # "{active} active · {total} available · {en} EN, {jp} JP, {es} ES selected".
        # Rebuilt on every refresh by _refresh_header_meta().
        self._meta_label = QLabel("")
        self._meta_label.setProperty("role", "meta")
        h_layout.addWidget(self._meta_label)
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

        # ── Active section: uppercase label on the left + hint on the right
        active_head = QHBoxLayout()
        active_head.setContentsMargins(0, 0, 0, 6)
        active_lbl = QLabel("ACTIVE SOURCES")
        active_lbl.setProperty("role", "section")
        active_head.addWidget(active_lbl)
        active_head.addStretch(1)
        active_hint = QLabel("Always included in search · used by manga in your library")
        active_hint.setProperty("role", "hint")
        active_head.addWidget(active_hint)
        self._content_layout.addLayout(active_head)

        self._active_container = QWidget()
        self._active_layout = QVBoxLayout(self._active_container)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(2)
        self._content_layout.addWidget(self._active_container)

        self._content_layout.addSpacing(T.PAD_LG)

        # ── All supported section ──
        supported_lbl = QLabel("ALL SUPPORTED SOURCES")
        supported_lbl.setProperty("role", "section")
        supported_lbl.setContentsMargins(0, 0, 0, 6)
        self._content_layout.addWidget(supported_lbl)

        # Toolbar row: filter + lang chips + sort dropdown.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        self._filter_entry = QLineEdit()
        self._filter_entry.setPlaceholderText("Filter sources by domain…")
        self._filter_entry.setMinimumWidth(220)
        self._filter_entry.setMaximumWidth(300)
        self._filter_entry.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._filter_entry)

        # Language chip-row (All / EN / JP / ES / Other). Selecting one
        # filters the supported list to sources tagged with that lang.
        self._lang_filter = "all"
        self._lang_chips: dict[str, QPushButton] = {}
        chips_wrap = QFrame()
        chips_wrap.setProperty("role", "card_2")
        chips_l = QHBoxLayout(chips_wrap)
        chips_l.setContentsMargins(3, 3, 3, 3)
        chips_l.setSpacing(0)
        for key, label in [("all","All"),("EN","EN"),("JP","JP"),
                            ("ES","ES"),("OTHER","Other")]:
            chip = QPushButton(label)
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "true" if key == self._lang_filter else "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, k=key: self._set_lang_filter(k))
            chips_l.addWidget(chip)
            self._lang_chips[key] = chip
        filter_row.addWidget(chips_wrap)

        filter_row.addStretch(1)

        from PySide6.QtWidgets import QComboBox
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Sort: A–Z", "Sort: Z–A", "Sort: Latency", "Sort: In library"])
        # Was setMaximumWidth(160) — the QSS reserves 28 px on the right
        # for the caret, leaving only ~130 px for text. "Sort: In library"
        # is 17 chars and clipped to "Sort: In librai". Use minimum
        # width sized to the widest label.
        self._sort_combo.setMinimumWidth(190)
        self._sort_combo.currentTextChanged.connect(lambda *_: self._render_supported())
        filter_row.addWidget(self._sort_combo)

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
        self._refresh_header_meta()
        self._render_active()
        self._render_supported()

    def _render_active(self):
        """Render active sources as a 3-col grid of accent-tinted cards
        (HTML spec.screens.sources.active_sources)."""
        return self._render_active_new()

    def _render_active_new(self):
        from PySide6.QtWidgets import QGridLayout

        # Drain all child widgets + sublayouts from the slot.
        for w in self._active_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._active_widgets.clear()
        while self._active_layout.count():
            it = self._active_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                sub = it.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    if si.widget():
                        si.widget().deleteLater()

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
            empty.setProperty("role", "hint")
            self._active_layout.addWidget(empty)
            self._active_widgets.append(empty)
            return

        all_health = self.app.app_state.get_all_source_health()
        color_map = {
            "ok": T.tokens()["status.success"],
            "warning": T.tokens()["status.warn"],
            "error": T.tokens()["status.danger"],
        }

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)

        for idx, (domain, titles) in enumerate(sorted(source_manga.items())):
            health = all_health.get(domain, {})
            dot_color = color_map.get(
                health.get("status", "unknown"), T.tokens()["text.t_3"],
            )
            latency = health.get("latency_ms")

            card = QFrame()
            card.setObjectName("active_src_card")
            card.setStyleSheet(
                f"#active_src_card {{"
                f"  background-color: {T.tokens()['surfaces.bg_1']};"
                f"  border: 1px solid {T.tokens()['accent.ring']};"
                f"  border-radius: 8px;"
                f"}}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(6)

            head = QHBoxLayout()
            head.setSpacing(6)
            head.setContentsMargins(0, 0, 0, 0)
            dot_lbl = QLabel("●")
            dot_lbl.setStyleSheet(f"color: {dot_color}; font-size: 11pt;")
            head.addWidget(dot_lbl)
            name = QLabel(domain)
            name.setStyleSheet(
                f"color: {T.tokens()['text.t_1']}; font-weight: 600; font-size: 13pt;"
            )
            head.addWidget(name, 1)
            # "..." more menu — opens a small QMenu with quick actions.
            more_btn = QPushButton("⋯")
            more_btn.setFixedSize(24, 22)
            more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            more_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" color: {T.tokens()['text.t_3']}; font-size: 14pt;"
                f" padding: 0; border-radius: 4px; }}"
                f"QPushButton:hover {{ background-color: {T.tokens()['surfaces.bg_2']};"
                f" color: {T.tokens()['text.t_1']}; }}"
            )
            more_btn.clicked.connect(lambda _, d=domain: self._show_active_more(d))
            head.addWidget(more_btn)
            cl.addLayout(head)

            meta_parts = [f"{len(titles)} manga in library", self._lang_of(domain)]
            if latency is not None:
                meta_parts.append(f"{latency}ms")
            meta = QLabel("  ·  ".join(meta_parts))
            meta.setStyleSheet(
                f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                f"color: {T.tokens()['text.t_3']};"
            )
            cl.addWidget(meta)

            row, col = divmod(idx, 3)
            grid.addWidget(card, row, col)
            self._active_widgets.append(card)

        for c in range(3):
            grid.setColumnStretch(c, 1)

        self._active_layout.addLayout(grid)

    def _render_active_DEPRECATED(self):
        # Old single-row rendering kept temporarily so blame/diff
        # readers can see the migration. Unreachable.
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
            row.setMinimumHeight(38)
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
        lang_key = getattr(self, "_lang_filter", "all")

        def _lang_match(s):
            if lang_key == "all":
                return True
            tag = self._lang_of(s)
            if lang_key == "OTHER":
                return tag not in ("EN", "JP", "ES")
            return tag == lang_key

        filtered = [
            s for s in self._all_sources
            if (not query or query in s.lower()) and _lang_match(s)
        ]

        disabled = set(self.app.config.get("sources.disabled", []) or [])

        # Per-source manga count (used for "{n} in library" + sort).
        per_source: dict[str, int] = {}
        for m in self.app.config.get("manga", []):
            for s in m.get("sources", []) or []:
                d = s.get("source", "")
                if d:
                    per_source[d] = per_source.get(d, 0) + 1
            d = m.get("source", "")
            if d:
                per_source[d] = per_source.get(d, 0) + 1

        # Sort dropdown — re-orders the filtered list before grouping.
        sort_choice = self._sort_combo.currentText() if hasattr(self, "_sort_combo") else "Sort: A–Z"
        if sort_choice == "Sort: Z–A":
            filtered.sort(reverse=True)
        elif sort_choice == "Sort: Latency":
            def _lat(s):
                hh = self.app.app_state.get_source_health(s) or {}
                return hh.get("latency_ms") or 10**9  # unpinged = bottom
            filtered.sort(key=_lat)
        elif sort_choice == "Sort: In library":
            filtered.sort(key=lambda s: -per_source.get(s, 0))
        else:
            filtered.sort()

        self._count_lbl.setText(f"{len(filtered)} of {len(self._all_sources)}")

        # Letter-group the filtered list (matches HTML spec.screens.sources
        # supported_sources.letter_group_head). Skipped when sorting by
        # something other than name — letter groups would look random.
        from collections import OrderedDict
        groups: OrderedDict[str, list[str]] = OrderedDict()
        group_by_letter = sort_choice in ("Sort: A–Z", "Sort: Z–A")
        if group_by_letter:
            for source in filtered:
                letter = (source[0] if source else "?").upper()
                if not letter.isalpha():
                    letter = "#"
                groups.setdefault(letter, []).append(source)
        else:
            groups[""] = filtered  # one big un-headered group

        for letter, sources_in_grp in groups.items():
            if letter:
                # Group header strip (only when sorting alphabetically)
                head = QFrame()
                head.setStyleSheet(
                    f"QFrame {{"
                    f"  background-color: {T.tokens()['surfaces.bg_2']};"
                    f"  border: none;"
                    f"}}"
                )
                head.setMinimumHeight(28)
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
                row_layout.setSpacing(10)

                check = QCheckBox()
                check.setChecked(source not in disabled)
                check.stateChanged.connect(
                    lambda _=None, s=source, c=check: self._on_toggle(s, c.isChecked())
                )
                row_layout.addWidget(check)

                # Status dot + name
                hh = self.app.app_state.get_source_health(source) or {}
                dot_color = {
                    "ok": T.tokens()["status.success"],
                    "warning": T.tokens()["status.warn"],
                    "error": T.tokens()["status.danger"],
                }.get(hh.get("status", "unknown"), T.tokens()["text.t_4"])
                dot = QLabel("●")
                dot.setStyleSheet(f"color: {dot_color}; font-size: 8pt;")
                row_layout.addWidget(dot)

                name = QLabel(source)
                name.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
                row_layout.addWidget(name, 1)

                # Lang tag — TINY chip, matches HTML CSS `.lang-tag`.
                # Plain colored text on a hair of transparent bg, no
                # boxed-in look. Just enough padding to read as a tag.
                lang_chip = QLabel(self._lang_of(source))
                lang_chip.setStyleSheet(
                    f"QLabel {{"
                    f"  color: {T.tokens()['text.t_3']};"
                    f"  font-family: 'Geist Mono', monospace;"
                    f"  font-size: 8pt; font-weight: 600;"
                    f"  letter-spacing: 0.5px;"
                    f"  padding: 0px 4px;"
                    f"}}"
                )
                lang_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lang_chip.setFixedWidth(28)
                row_layout.addWidget(lang_chip)

                # Latency (if pinged) — fixed-width mono so columns align
                lat = QLabel(f"{hh['latency_ms']}ms" if hh.get("latency_ms") is not None else "—")
                lat.setStyleSheet(
                    f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                    f"color: {T.tokens()['text.t_3']};"
                )
                lat.setFixedWidth(64)
                lat.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row_layout.addWidget(lat)

                # "{n} manga" count column — always present so columns line up
                n = per_source.get(source, 0)
                used = QLabel(f"{n} manga")
                used.setStyleSheet(
                    f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                    f"color: {T.tokens()['text.t_3'] if n == 0 else T.tokens()['text.t_2']};"
                )
                used.setFixedWidth(76)
                used.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
