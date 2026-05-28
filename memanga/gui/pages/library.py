"""
Library page — main home view with grid/list, filters, stats bar.
"""

from datetime import datetime
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QScrollArea, QWidget, QGridLayout, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from .base import BasePage
from .. import theme as T
from ..components.manga_card import MangaCard
from ..components.manga_row import MangaRow
from ..components.context_menu import ContextMenu
from ..components.toast import Toast
from ..components.dialogs import ConfirmDialog


class LibraryPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._view_mode = "grid"
        self._filter_status = "all"
        self._search_query = ""
        self._sort_by = self.app.config.get("gui.sort_by", "title")
        self._cards: list = []

        self._build()

        self.app.events.subscribe("cover_loaded", self._on_cover_loaded)
        self.app.events.subscribe("check_complete", lambda d: self._on_check_done())
        self.app.events.subscribe("download_complete", lambda d: self._on_check_done())
        # Issue #18: repaint cards when a chapter is opened in the reader
        # so the "Read X/N" sub-line + cover progress bar update live.
        self.app.events.subscribe("chapter_read", lambda d: self._on_check_done())
        # Refresh when something edits/adds/removes a manga elsewhere
        # (Add Manga dialog, Detail page, cover backfill writes a URL).
        self.app.events.subscribe("library_updated", lambda d: self._on_check_done())
        # Silent auto-checks (no new chapters) still need to bump the
        # "Synced just now" stamp — otherwise it stays at the same
        # value for as long as the user is on the Library tab.
        self.app.events.subscribe("check_complete_silent",
                                    lambda d: self._refresh_meta_only())

        # Tick the "Synced Xm ago" stamp once a minute while the page
        # is visible. Without this it freezes at the value rendered
        # when on_show fired and only updates on tab-switch.
        from PySide6.QtCore import QTimer as _QT
        self._meta_tick = _QT(self)
        self._meta_tick.timeout.connect(self._refresh_meta_only)
        self._meta_tick.start(30_000)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Page header (with bottom divider, per new spec) ──
        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Library")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)

        # Per spec: "Check all" ghost (refresh icon), "Add manga" primary (plus icon).
        from ..assets.icons import icon as _ic
        check_btn = QPushButton("  Check all")
        check_btn.setProperty("variant", "ghost")
        check_btn.setIcon(_ic("refresh", T.tokens()["text.t_2"], 14))
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self._check_all)
        top_row.addWidget(check_btn)

        add_btn = QPushButton("  Add manga")
        add_btn.setProperty("variant", "primary")
        add_btn.setIcon(_ic("plus", T.tokens()["accent.on_primary"], 14))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._open_add_dialog)
        top_row.addWidget(add_btn)
        h_layout.addLayout(top_row)

        # Multi-part meta line: "{n} manga · {ch} chapters · {unread} unread · Synced {ago}"
        # Render a placeholder so the header height is stable from the
        # very first paint; the real numbers fill in once on_show fires.
        self._stats_label = QLabel("0 manga  ·  0 chapters tracked  ·  0 read  ·  0 unread  ·  Synced never")
        self._stats_label.setProperty("role", "meta")
        h_layout.addWidget(self._stats_label)

        layout.addWidget(header)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ── Body wrapper ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 20, 32, 20)
        body_layout.setSpacing(T.PAD_SM)
        layout.addWidget(body, 1)

        # Filter bar — per design spec, search + status chip-row + sort dropdown.
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Filter library…")
        self._search_entry.setMaximumWidth(240)
        self._search_entry.textChanged.connect(self._on_search)
        filter_bar.addWidget(self._search_entry)

        # Status chip-row instead of a dropdown — matches HTML.
        self._chip_buttons: dict[str, QPushButton] = {}
        chips_wrap = QFrame()
        chips_wrap.setProperty("role", "card_2")
        chips_l = QHBoxLayout(chips_wrap)
        chips_l.setContentsMargins(3, 3, 3, 3)
        chips_l.setSpacing(0)
        for key, label in [("all","All"),("reading","Reading"),("plan","Plan"),
                            ("on-hold","Paused"),("completed","Complete")]:
            chip = QPushButton(label)
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "true" if key == self._filter_status else "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, k=key: self._set_chip_filter(k))
            chips_l.addWidget(chip)
            self._chip_buttons[key] = chip
        filter_bar.addWidget(chips_wrap)

        # Kept as a hidden combobox to preserve back-compat for callers
        # that probe ._status_filter; not displayed.
        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "Reading", "On-hold", "Dropped", "Completed"])
        self._status_filter.hide()

        filter_bar.addStretch()

        self._sort_menu = QComboBox()
        self._sort_menu.addItems(["Title A-Z", "Last Updated", "Recently Added", "Chapter Count", "Status"])
        sort_display = {"title": "Title A-Z", "last_updated": "Last Updated",
                        "recently_added": "Recently Added", "chapter_count": "Chapter Count",
                        "status": "Status"}
        self._sort_menu.setCurrentText(sort_display.get(self._sort_by, "Title A-Z"))
        self._sort_menu.currentTextChanged.connect(self._on_sort_change)
        filter_bar.addWidget(self._sort_menu)

        # View-toggle chip row (grid / list) — persisted via gui.view_mode.
        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        view_wrap = QFrame()
        view_wrap.setProperty("role", "card_2")
        view_l = QHBoxLayout(view_wrap)
        view_l.setContentsMargins(3, 3, 3, 3)
        view_l.setSpacing(0)
        self._view_buttons: dict[str, QPushButton] = {}
        self._view_mode = self.app.config.get("gui.view_mode", "grid")
        for mode, glyph in [("grid", "▦"), ("list", "≡")]:
            btn = QPushButton(glyph)
            btn.setProperty("variant", "chip")
            btn.setProperty("active", "true" if mode == self._view_mode else "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedWidth(34)
            btn.clicked.connect(lambda _, m=mode: self._set_view_mode(m))
            view_l.addWidget(btn)
            self._view_buttons[mode] = btn
        filter_bar.addWidget(view_wrap)

        self._count_label = QLabel("")
        self._count_label.setProperty("role", "meta")
        filter_bar.addWidget(self._count_label)

        body_layout.addLayout(filter_bar)

        # ── Continue Reading rail ──
        # Rebuilt on each refresh. Holds up to 4 ContinueCard widgets in
        # a horizontal grid; hidden entirely when there's nothing to
        # continue.
        self._continue_section = QWidget()
        cs_l = QVBoxLayout(self._continue_section)
        cs_l.setContentsMargins(0, 4, 0, 0)
        cs_l.setSpacing(8)

        cs_head = QHBoxLayout()
        cs_head_lbl = QLabel("CONTINUE READING")
        cs_head_lbl.setProperty("role", "section")
        cs_head.addWidget(cs_head_lbl)
        cs_head.addStretch(1)
        self._continue_count_lbl = QLabel("0")
        self._continue_count_lbl.setProperty("role", "mono_meta")
        cs_head.addWidget(self._continue_count_lbl)
        cs_l.addLayout(cs_head)

        self._continue_grid = QGridLayout()
        self._continue_grid.setSpacing(12)
        cs_l.addLayout(self._continue_grid)
        body_layout.addWidget(self._continue_section)

        # ALL MANGA section label (between filter and grid) — matches HTML.
        all_label = QLabel("ALL MANGA")
        all_label.setProperty("role", "section")
        all_label.setContentsMargins(0, 16, 0, 8)
        body_layout.addWidget(all_label)

        # Scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._grid_layout = QGridLayout(self._scroll_content)
        self._grid_layout.setSpacing(T.PAD_MD)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._scroll_content)
        body_layout.addWidget(self._scroll, 1)

    def on_show(self, **kwargs):
        self._refresh()
        # Remember the grid column count we just laid out for so resize
        # events can tell whether they need to re-layout or not.
        self._last_grid_cols = self._current_col_count()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # When the window changes size enough that the manga grid needs
        # a different number of columns (e.g. fullscreen toggle), the
        # existing card positions stay in their old slots until the
        # next refresh. Detect that and re-layout the grid in place.
        try:
            new_cols = self._current_col_count()
            if new_cols != getattr(self, "_last_grid_cols", -1):
                self._last_grid_cols = new_cols
                # Defer to next event tick so the scroll area has its
                # final width when we recompute.
                from PySide6.QtCore import QTimer as _QT
                _QT.singleShot(0, self._relayout_grid)
        except Exception:
            pass

    def _current_col_count(self) -> int:
        if not hasattr(self, "_scroll") or not self._scroll:
            return -1
        cols = max(1, (self._scroll.width() - 40) // (T.CARD_WIDTH + T.PAD_MD))
        return int(cols)

    def _relayout_grid(self):
        """Re-position the existing card widgets into the new column
        count without rebuilding them (preserves loaded covers + hover
        state). Cheap compared to a full `_refresh()`.
        """
        if self._view_mode != "grid" or not self._cards:
            return
        cols = self._current_col_count()
        if cols <= 0:
            return
        # Detach + re-add in row/col order.
        for i, (_m, card) in enumerate(self._cards):
            self._grid_layout.removeWidget(card)
        for i, (_m, card) in enumerate(self._cards):
            row = i // cols
            col = i % cols
            self._grid_layout.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop)

    def _refresh_meta_only(self):
        """Lightweight refresh — only updates the "Synced Xm ago" meta
        line. Avoids rebuilding the whole grid (and re-fetching every
        cover) just to bump a timestamp.
        """
        try:
            from datetime import datetime
            stats = self.app.app_state.get_stats()
            last_check = self.app.app_state.get("last_check")
            check_text = "never"
            if last_check:
                try:
                    elapsed = (datetime.now() - datetime.fromisoformat(last_check)).total_seconds()
                    if elapsed < 60:
                        check_text = "just now"
                    elif elapsed < 3600:
                        check_text = f"{int(elapsed // 60)}m ago"
                    elif elapsed < 86400:
                        check_text = f"{int(elapsed // 3600)}h ago"
                    else:
                        check_text = f"{int(elapsed // 86400)}d ago"
                except Exception:
                    pass
            unread_total = sum(
                self.app.app_state.get_new_chapters(m.get("title", ""))
                for m in self.app.config.get("manga", [])
            )
            read_total = sum(
                self.app.app_state.get_read_count(m.get("title", ""))
                for m in self.app.config.get("manga", [])
            )
            self._stats_label.setText(
                f"{stats['total_manga']} manga  ·  {stats['total_chapters']} chapters tracked  "
                f"·  {read_total} read  ·  {unread_total} unread  "
                f"·  Synced {check_text}"
            )
        except Exception:
            # Tick must never raise — it fires on a timer.
            pass

    def _refresh(self):
        # Continue Reading rail first
        self._refresh_continue_rail()

        # Clear grid
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        manga_list = self._get_filtered_manga()

        # Update stats
        stats = self.app.app_state.get_stats()
        last_check = self.app.app_state.get("last_check")
        check_text = "never"
        if last_check:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(last_check)).total_seconds()
                if elapsed < 60:
                    check_text = "just now"
                elif elapsed < 3600:
                    check_text = f"{int(elapsed // 60)}m ago"
                elif elapsed < 86400:
                    check_text = f"{int(elapsed // 3600)}h ago"
                else:
                    check_text = f"{int(elapsed // 86400)}d ago"
            except Exception:
                pass
        # Multi-part meta line per design spec: count \u00b7 chapters \u00b7 read \u00b7 unread \u00b7 synced.
        unread_total = sum(
            self.app.app_state.get_new_chapters(m.get("title", ""))
            for m in self.app.config.get("manga", [])
        )
        # Issue #18: total chapters read across the whole library.
        read_total = sum(
            self.app.app_state.get_read_count(m.get("title", ""))
            for m in self.app.config.get("manga", [])
        )
        self._stats_label.setText(
            f"{stats['total_manga']} manga  \u00b7  {stats['total_chapters']} chapters tracked  "
            f"\u00b7  {read_total} read  \u00b7  {unread_total} unread  "
            f"\u00b7  Synced {check_text}"
        )
        # "10 of 10 shown" format from spec.
        total_manga = stats['total_manga']
        self._count_label.setText(f"{len(manga_list)} of {total_manga} shown")

        if not manga_list:
            empty = QLabel("No manga tracked yet. Click '+ Add' to get started.")
            empty.setStyleSheet(f"color: {T.FG_MUTED}; font-size: {T.FONT_SIZE_MD}pt; padding: 60px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid_layout.addWidget(empty, 0, 0)
            return

        if self._view_mode == "grid":
            self._build_grid(manga_list)
        else:
            self._build_list(manga_list)

    def _build_grid(self, manga_list):
        cols = max(1, (self._scroll.width() - 40) // (T.CARD_WIDTH + T.PAD_MD))
        if cols < 1:
            cols = 4

        for i, manga in enumerate(manga_list):
            cover_url = manga.get("cover_url")
            cover_img = self.app.cover_cache.get_cover(cover_url, size=(T.CARD_WIDTH, T.CARD_COVER_HEIGHT))
            title = manga.get("title", "")
            new_count = self.app.app_state.get_new_chapters(title)
            # Issue #18: pass per-chapter read / total counts so the card
            # can render "Read X/N" and a read-based progress bar.
            read_count = self.app.app_state.get_read_count(title)
            total_count = len(self.app.app_state.get_available_chapters(title) or [])

            card = MangaCard(
                self._scroll_content, manga=manga, cover_image=cover_img,
                on_click=self._on_manga_click,
                on_right_click=self._on_right_click,
                new_count=new_count,
                read_count=read_count,
                total_count=total_count,
            )
            row = i // cols
            col = i % cols
            self._grid_layout.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop)
            self._cards.append((manga, card))

    def _build_list(self, manga_list):
        for i, manga in enumerate(manga_list):
            title = manga.get("title", "")
            state_data = self.app.app_state.get_manga_state(title)
            cover_url = manga.get("cover_url")
            thumb = self.app.cover_cache.get_cover(cover_url, size=(36, 48)) if cover_url else None
            new_count = self.app.app_state.get_new_chapters(title)

            row = MangaRow(
                self._scroll_content, manga=manga, state_data=state_data,
                cover_image=thumb, on_click=self._on_manga_click,
                on_right_click=self._on_right_click, new_count=new_count,
            )
            self._grid_layout.addWidget(row, i, 0)
            self._cards.append((manga, row))

    def _get_filtered_manga(self):
        manga_list = self.app.config.get("manga", [])
        results = []
        for m in manga_list:
            status = m.get("status", "reading")
            if self._filter_status != "all" and status != self._filter_status:
                continue
            if self._search_query and self._search_query.lower() not in m.get("title", "").lower():
                continue
            results.append(m)

        sort_key = self._sort_by
        if sort_key == "title":
            results.sort(key=lambda m: m.get("title", "").lower())
        elif sort_key in ("last_updated", "recently_added", "chapter_count"):
            cache = {m.get("title", ""): self.app.app_state.get_manga_state(m.get("title", "")) for m in results}
            if sort_key == "last_updated":
                results.sort(key=lambda m: cache.get(m.get("title", ""), {}).get("last_updated") or "", reverse=True)
            elif sort_key == "recently_added":
                results.sort(key=lambda m: cache.get(m.get("title", ""), {}).get("created") or "", reverse=True)
            elif sort_key == "chapter_count":
                results.sort(key=lambda m: len(cache.get(m.get("title", ""), {}).get("downloaded", [])), reverse=True)
        elif sort_key == "status":
            order = {"reading": 0, "on-hold": 1, "completed": 2, "dropped": 3}
            results.sort(key=lambda m: order.get(m.get("status", "reading"), 4))
        return results

    def _refresh_continue_rail(self):
        """Repopulate the Continue Reading rail with up to 4 most-recently-read
        manga that have an unfinished chapter."""
        from ..components.continue_card import ContinueCard
        # Drain old cards
        while self._continue_grid.count():
            item = self._continue_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        candidates = []
        for m in self.app.config.get("manga", []) or []:
            title = m.get("title", "")
            if not title:
                continue
            state = self.app.app_state.get_manga_state(title) or {}
            last_chapter = state.get("last_chapter")
            if not last_chapter:
                continue
            # Skip completed/dropped from rail
            if m.get("status") in ("completed", "dropped"):
                continue
            # Sort key = last_updated timestamp (most recent first)
            candidates.append((state.get("last_updated") or "", m, state))

        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[:4]

        self._continue_section.setVisible(bool(candidates))
        self._continue_count_lbl.setText(str(len(candidates)))
        if not candidates:
            return

        for col, (_, m, state) in enumerate(candidates):
            cover = self.app.cover_cache.get_cover(m.get("cover_url"), size=(48, 68))
            try:
                done = len(state.get("downloaded", []))
                total = int(m.get("chapters_total") or done * 2 or 1)
                pct = min(100, (done / max(total, 1)) * 100)
            except Exception:
                pct = 0
            card = ContinueCard(
                self._scroll_content, manga=m, cover_pixmap=cover,
                last_chapter=str(state.get("last_chapter", "")),
                progress_pct=pct,
                on_click=lambda mm: self.app.show_page("detail", manga=mm),
            )
            self._continue_grid.addWidget(card, 0, col)

    def _on_search(self, text):
        self._search_query = text.strip()
        self._refresh()

    def _on_status_filter(self, value):
        self._filter_status = value.lower() if value != "All" else "all"
        self._refresh()

    def _set_chip_filter(self, key: str):
        """Status chip clicked — update filter + refresh chip active states."""
        self._filter_status = key
        for k, btn in self._chip_buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh()

    def _set_view_mode(self, mode: str):
        """Toggle grid vs list view. Persisted in config."""
        if mode not in ("grid", "list") or mode == self._view_mode:
            return
        self._view_mode = mode
        for m, btn in self._view_buttons.items():
            btn.setProperty("active", "true" if m == mode else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
        self.app.config.set("gui.view_mode", mode)
        self.app.config.save()
        self._refresh()

    def _on_sort_change(self, value):
        sort_map = {"Title A-Z": "title", "Last Updated": "last_updated",
                     "Recently Added": "recently_added", "Chapter Count": "chapter_count",
                     "Status": "status"}
        self._sort_by = sort_map.get(value, "title")
        self.app.config.set("gui.sort_by", self._sort_by)
        self.app.config.save()
        self._refresh()

    def _on_manga_click(self, manga):
        self.app.show_page("detail", manga=manga)

    def _on_right_click(self, manga, x, y):
        items = [
            ("Check Updates", lambda: self._ctx_check(manga)),
            ("Download All", lambda: self._ctx_download_all(manga)),
            (None, None),
            ("Set: Reading", lambda: self._ctx_set_status(manga, "reading")),
            ("Set: On-hold", lambda: self._ctx_set_status(manga, "on-hold")),
            ("Set: Completed", lambda: self._ctx_set_status(manga, "completed")),
            (None, None),
            ("Remove", lambda: self._ctx_remove(manga)),
        ]
        ContextMenu(self, x, y, items)

    def _ctx_check(self, manga):
        self.app.worker.check_updates([manga], self.app.app_state, self.app.config)
        self.app.show_page("downloads")

    def _ctx_download_all(self, manga):
        # Issue #15: don't wipe the `downloaded` list — that's what was
        # causing already-on-disk (already read) chapters to be queued
        # again. We only reset `last_chapter` so check_for_updates returns
        # the full chapter list, then the queue step in DownloadsPage
        # skips anything `is_chapter_downloaded` already covers.
        title = manga.get("title", "")
        self.app.app_state.set_last_chapter(title, None)
        self.app.worker.check_updates([manga], self.app.app_state, self.app.config)
        self.app.show_page("downloads")

    def _ctx_set_status(self, manga, status):
        for m in self.app.config.get("manga", []):
            if m.get("title") == manga.get("title"):
                m["status"] = status
                break
        self.app.config.save()
        self._refresh()

    def _ctx_remove(self, manga):
        title = manga.get("title", "Unknown")
        ConfirmDialog(self, title="Remove", message=f"Remove '{title}'?",
                      on_confirm=lambda: self._do_remove(title))

    def _do_remove(self, title):
        manga_list = [m for m in self.app.config.get("manga", []) if m.get("title") != title]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self.app.app_state.remove_manga(title)
        self.app.events.publish(
            "library_updated", {"title": title, "action": "remove"}
        )
        self._refresh()

    def _open_add_dialog(self, prefill=None):
        from .add_manga import AddMangaDialog
        dialog = AddMangaDialog(self, self.app, prefill=prefill)
        dialog.exec()
        self._refresh()

    def _check_all(self):
        # Pre-flight check — if we already know we're offline, tell
        # the user instead of queueing a job that will instantly
        # publish a check_error.
        net = getattr(self.app, "network", None)
        if net is not None and not net.is_online:
            Toast(self,
                   "You're offline — connect to check for updates.",
                   kind="warn")
            return
        manga_list = self.app.config.get("manga", [])
        if manga_list:
            self.app.worker.check_updates(manga_list, self.app.app_state, self.app.config)
            Toast(self, "Checking for updates...", kind="info")

    def _on_cover_loaded(self, data):
        if not hasattr(self, "_cover_pending") or not self._cover_pending:
            self._cover_pending = True
            QTimer.singleShot(500, self._debounced_cover_refresh)

    def _debounced_cover_refresh(self):
        self._cover_pending = False
        if self.isVisible():
            self._refresh()

    def _on_check_done(self):
        if self.isVisible():
            QTimer.singleShot(300, self._refresh)
