"""
Library page — main home view with grid/list, filters, stats bar.
"""

from datetime import datetime
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QScrollArea, QWidget, QGridLayout, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence
from .base import BasePage
from ...perf import timed
from .. import theme as T
from ..theme.tokens import STATUS_ORDER, status_label
from ..components.manga_card import MangaCard
from ..components.manga_row import MangaRow
from ..components.context_menu import ContextMenu
from ..focus import focus_into
from ..components.toast import Toast
from ..components.wrapping_label import WrappingLabel
from ..components.remove_manga_modal import (RemoveMangaModal, remove_manga,
                                              removed_message)

# Left and right margin of the page body, in px.
_BODY_MARGIN = 32
# Narrowest the filter box may get while the chips share its row: wide
# enough to read its placeholder.
_FILTER_MIN_WIDTH = 200


class LibraryPage(BasePage):
    # Queued like the page handoff in MeMangaApp.show_page (issue #396):
    # the rebuilt cards are shown by events posted before it.
    _refocus_due = Signal(str)

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._refocus_due.connect(self._refocus_card,
                                  Qt.ConnectionType.QueuedConnection)
        self._view_mode = "grid"
        self._filter_status = "all"
        self._search_query = ""
        self._sort_by = self.app.config.get("gui.sort_by", "title")
        self._cards: list = []
        # Continue Reading cards as (manga, card), for in-place cover
        # updates like the grid's.
        self._continue_cards: list = []
        # Coalesces event-driven refreshes (check/download/read/library
        # events) so a burst - e.g. every chapter of a batch download
        # completing - triggers one grid rebuild, not one per event.
        self._refresh_pending = False
        # Debounces the filter box: rebuilding the grid on every
        # keystroke made typing feel laggy on larger libraries.
        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(250)
        self._filter_debounce.timeout.connect(self._on_filter_debounce)

        self._build()

        self.app.events.subscribe("cover_loaded", self._on_cover_loaded)
        self.app.events.subscribe("check_complete", lambda d: self._on_check_done())
        self.app.events.subscribe("download_complete", lambda d: self._on_check_done())
        # Issue #18: repaint cards when a chapter is opened in the reader
        # so the "Read X/N" sub-line + cover progress bar update live.
        self.app.events.subscribe("chapter_read", lambda d: self._on_check_done())
        # Issue #389: remove-after-read may land after the reader was left.
        self.app.events.subscribe("chapter_removed", lambda d: self._on_check_done())
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
        # Wraps at the minimum window width instead of losing its end.
        self._stats_label = WrappingLabel("0 manga  ·  0 chapters tracked  ·  0 read  ·  0 unread  ·  Synced never")
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
        body_layout.setContentsMargins(_BODY_MARGIN, 20, _BODY_MARGIN, 20)
        body_layout.setSpacing(T.PAD_SM)
        layout.addWidget(body, 1)

        # Filter bar — per design spec, search + status chip-row + sort dropdown.
        # One row when the page is wide enough; otherwise the status chips
        # get a second row of their own (see _fit_filter_bar), so nothing
        # is cut off at the default or the minimum window size.
        self._filter_bar = QWidget()
        bar_l = QVBoxLayout(self._filter_bar)
        bar_l.setContentsMargins(0, 0, 0, 0)
        bar_l.setSpacing(T.PAD_SM)
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)
        self._filter_row = filter_bar
        bar_l.addLayout(filter_bar)
        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(10)
        bar_l.addLayout(self._chip_row)
        self._chips_on_own_row = False

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Filter library…")
        self._search_entry.setAccessibleName("Filter library")
        self._search_entry.setMaximumWidth(240)
        self._search_entry.textChanged.connect(self._on_search)
        filter_bar.addWidget(self._search_entry)
        # Ctrl/Cmd+F → filter field (issue #396).
        self.add_shortcut(QKeySequence.StandardKey.Find,
                          lambda: self.focus_field(self._search_entry))

        # Status chip-row instead of a dropdown — matches HTML.
        self._chip_buttons: dict[str, QPushButton] = {}
        chips_wrap = QFrame()
        chips_wrap.setProperty("role", "card_2")
        chips_l = QHBoxLayout(chips_wrap)
        chips_l.setContentsMargins(3, 3, 3, 3)
        chips_l.setSpacing(0)
        # Every status a manga can have, in the wording used everywhere
        # else ("Plan" is short for "Plan to read", to keep the row
        # narrow; its tooltip and accessible name give the full label).
        for key in ("all", *STATUS_ORDER):
            full = "All" if key == "all" else status_label(key)
            chip = QPushButton("Plan" if key == "plan" else full)
            if key == "plan":
                chip.setToolTip(full)
                chip.setAccessibleName(full)
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "true" if key == self._filter_status else "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, k=key: self._set_chip_filter(k))
            chips_l.addWidget(chip)
            self._chip_buttons[key] = chip
        filter_bar.addWidget(chips_wrap)
        self._chips_wrap = chips_wrap

        # Kept as a hidden combobox to preserve back-compat for callers
        # that probe ._status_filter; not displayed.
        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "Reading", "On-hold", "Dropped", "Completed"])
        self._status_filter.hide()

        filter_bar.addStretch()

        self._sort_menu = QComboBox()
        # Qt on Linux publishes a combo box's current item as its name, so
        # the purpose also goes in the description, which every platform
        # publishes.
        self._sort_menu.setAccessibleName("Sort library")
        self._sort_menu.setAccessibleDescription("Sort order of the library")
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
        for mode, glyph, label in [("grid", "▦", "Grid view"),
                                   ("list", "≡", "List view")]:
            btn = QPushButton(glyph)
            # The glyph alone is not a label (issue #394).
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            btn.setProperty("variant", "chip")
            btn.setProperty("active", "true" if mode == self._view_mode else "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedWidth(34)
            btn.clicked.connect(lambda _, m=mode: self._set_view_mode(m))
            view_l.addWidget(btn)
            self._view_buttons[mode] = btn
        self._describe_view_buttons()
        filter_bar.addWidget(view_wrap)
        self._view_wrap = view_wrap

        body_layout.addWidget(self._filter_bar)

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
        # The "N of M shown" count sits at its right end, like the count
        # of the Continue Reading section; in the filter bar it left no
        # room for the status chips at the default window width.
        all_head = QHBoxLayout()
        all_head.setContentsMargins(0, 16, 0, 8)
        all_label = QLabel("ALL MANGA")
        all_label.setProperty("role", "section")
        all_head.addWidget(all_label)
        all_head.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setProperty("role", "mono_meta")
        all_head.addWidget(self._count_label)
        body_layout.addLayout(all_head)

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
        self._fit_filter_bar(self.width())
        self._refresh()
        # Remember the grid column count we just laid out for so resize
        # events can tell whether they need to re-layout or not.
        self._last_grid_cols = self._current_col_count()

    def _filter_bar_one_row_width(self) -> int:
        """Width the filter bar needs to keep the chips beside the
        filter box, with the box still wide enough to show its
        placeholder."""
        spacing = self._filter_row.spacing()
        return (_FILTER_MIN_WIDTH
                + self._chips_wrap.sizeHint().width()
                + self._sort_menu.sizeHint().width()
                + self._view_wrap.sizeHint().width()
                + 4 * spacing)

    def _fit_filter_bar(self, page_width: int):
        """Move the status chips to a row of their own when the page is
        too narrow for one row, and back when it is wide enough again.
        Tab order follows what is on screen, row by row."""
        if not hasattr(self, "_chips_wrap"):
            return
        available = page_width - 2 * _BODY_MARGIN
        own_row = available < self._filter_bar_one_row_width()
        if own_row == self._chips_on_own_row:
            return
        self._chips_on_own_row = own_row
        chips = self._chips_wrap
        if own_row:
            self._filter_row.removeWidget(chips)
            self._chip_row.addWidget(chips, 0, Qt.AlignmentFlag.AlignLeft)
            order = [self._search_entry, self._sort_menu,
                     *self._view_buttons.values(),
                     *self._chip_buttons.values()]
        else:
            self._chip_row.removeWidget(chips)
            self._filter_row.insertWidget(1, chips)
            order = [self._search_entry, *self._chip_buttons.values(),
                     self._sort_menu, *self._view_buttons.values()]
        for first, second in zip(order, order[1:]):
            QWidget.setTabOrder(first, second)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_filter_bar(ev.size().width())
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
            self._update_stats_label()
        except Exception:
            # Tick must never raise — it fires on a timer.
            pass

    def _synced_text(self) -> str:
        """How long ago the last check finished: "never", "just now",
        "5m ago", "3h ago" or "2d ago"."""
        last_check = self.app.app_state.get("last_check")
        if not last_check:
            return "never"
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_check)).total_seconds()
        except Exception:
            return "never"
        if elapsed < 60:
            return "just now"
        if elapsed < 3600:
            return f"{int(elapsed // 60)}m ago"
        if elapsed < 86400:
            return f"{int(elapsed // 3600)}h ago"
        return f"{int(elapsed // 86400)}d ago"

    def _update_stats_label(self) -> dict:
        """Write the header meta line: count · chapters · read · unread
        · synced. Returns the tracked-manga stats it used."""
        stats = self._tracked_stats()
        manga_list = self.app.config.get("manga", []) or []
        unread_total = sum(
            self.app.app_state.get_new_chapters(m.get("title", ""))
            for m in manga_list
        )
        # Issue #18: total chapters read across the whole library.
        read_total = sum(
            self.app.app_state.get_read_count(m.get("title", ""))
            for m in manga_list
        )
        self._stats_label.setText(
            f"{stats['total_manga']} manga  \u00b7  {stats['total_chapters']} chapters tracked  "
            f"\u00b7  {read_total} read  \u00b7  {unread_total} unread  "
            f"\u00b7  Synced {self._synced_text()}"
        )
        return stats

    def _tracked_stats(self):
        """Header counts for tracked manga only. Removing a manga can
        keep its state entry (issue #392), which must not be counted."""
        titles = [m.get("title", "") for m in self.app.config.get("manga", []) or []]
        return {
            "total_manga": len(titles),
            "total_chapters": sum(
                len(self.app.app_state.get_downloaded_chapters(t)) for t in titles
            ),
        }

    @timed("gui.library.refresh")
    def _refresh(self):
        # Continue Reading rail first
        self._refresh_continue_rail()

        # Clear grid. Hidden first: deleteLater leaves the old cards on
        # screen and focusable until control returns to the event loop
        # (issue #396).
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._cards.clear()

        manga_list = self._get_filtered_manga()

        stats = self._update_stats_label()
        # "10 of 10 shown" format from spec.
        total_manga = stats['total_manga']
        self._count_label.setText(f"{len(manga_list)} of {total_manga} shown")

        if not manga_list:
            self._grid_layout.addWidget(self._empty_state(total_manga), 0, 0)
            return

        if self._view_mode == "grid":
            self._build_grid(manga_list)
        else:
            self._build_list(manga_list)

    def _empty_state(self, total_manga: int) -> QLabel:
        """The text shown instead of the grid: how to start on a new
        library (and where downloads will go, issue #370), or that the
        filter matches nothing."""
        if total_manga:
            text = ("No manga match the current filter.\n"
                    "Clear the filter box or choose All to see your library.")
        else:
            text = ("No manga tracked yet.\n"
                    "Use Add manga above, or Search, to get started.\n\n"
                    f"Downloads are saved to {self.app.config.download_dir}\n"
                    "You can change the folder in Settings.")
        empty = QLabel(text)
        # A folder path is user text; show it literally.
        empty.setTextFormat(Qt.TextFormat.PlainText)
        empty.setProperty("role", "empty")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        return empty

    def _card_cover(self, cover_url):
        """Cover for a grid card, or None when there is no real one yet,
        so the card paints its own titled placeholder."""
        cover = self.app.cover_cache.get_cover(
            cover_url, size=(T.CARD_WIDTH, T.CARD_COVER_HEIGHT))
        if self.app.cover_cache.is_placeholder(cover):
            return None
        return cover

    def _build_grid(self, manga_list):
        cols = max(1, (self._scroll.width() - 40) // (T.CARD_WIDTH + T.PAD_MD))
        if cols < 1:
            cols = 4

        for i, manga in enumerate(manga_list):
            cover_img = self._card_cover(manga.get("cover_url"))
            title = manga.get("title", "")
            new_count = self.app.app_state.get_new_chapters(title)
            # Issue #18: pass per-chapter read / total counts so the card
            # can render "Read X/N" and a read-based progress bar.
            read_count = self.app.app_state.get_read_count(title)
            total_count = self.app.app_state.get_available_chapter_count(title)

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
            order = {status: i for i, status in enumerate(STATUS_ORDER)}
            order["paused"] = order["on-hold"]  # older spelling
            results.sort(key=lambda m: order.get(m.get("status", "reading"),
                                                 len(order)))
        return results

    def _refresh_continue_rail(self):
        """Repopulate the Continue Reading rail with up to 4 manga, the
        most recently read first.

        "Read" means opened in the built-in reader: the rail follows the
        reading cursor, not the newest downloaded chapter (which it used
        to show as "last read" for manga that were never opened).
        """
        from ..components.continue_card import ContinueCard
        # Drain old cards (hidden first, as in _refresh)
        while self._continue_grid.count():
            item = self._continue_grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._continue_cards.clear()

        candidates = []
        for m in self.app.config.get("manga", []) or []:
            title = m.get("title", "")
            if not title:
                continue
            # Skip completed/dropped from rail
            if m.get("status") in ("completed", "dropped"):
                continue
            progress = self.app.app_state.get_reading_progress(title) or {}
            chapter = progress.get("last_chapter")
            if not chapter:
                continue
            candidates.append((progress.get("last_read") or "", m, str(chapter)))

        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[:4]

        self._continue_section.setVisible(bool(candidates))
        self._continue_count_lbl.setText(str(len(candidates)))
        if not candidates:
            return

        for col, (_, m, chapter) in enumerate(candidates):
            title = m.get("title", "")
            cover = self.app.cover_cache.get_cover(m.get("cover_url"), size=(48, 68))
            # Read chapters out of those known for the manga; an unknown
            # total shows an empty bar rather than a made-up half.
            total = self.app.app_state.get_available_chapter_count(title)
            read = self.app.app_state.get_read_count(title)
            pct = min(100, (read / total) * 100) if total > 0 else 0
            card = ContinueCard(
                self._scroll_content, manga=m, cover_pixmap=cover,
                last_chapter=chapter,
                progress_pct=pct,
                on_click=lambda mm, ch=chapter: self._continue_reading(mm, ch),
            )
            self._continue_grid.addWidget(card, 0, col)
            self._continue_cards.append((m, card))

    def _continue_reading(self, manga, chapter):
        """Open the reader where the user left off; the Detail page when
        that chapter's download is no longer there."""
        title = manga.get("title", "")
        if self.app.app_state.is_chapter_downloaded(title, chapter):
            self.app.show_page("reader", manga=manga, chapter=chapter)
        else:
            self.app.show_page("detail", manga=manga)

    def _on_search(self, text):
        self._search_query = text.strip()
        # Restart on each keystroke - the grid rebuilds once, when the
        # user pauses typing.
        self._filter_debounce.start()

    def _on_filter_debounce(self):
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
        self._describe_view_buttons()
        self.app.config.set("gui.view_mode", mode)
        self.app.config.save()
        self._refresh()

    def _describe_view_buttons(self):
        """Say which view is current; the accent tint is visual only.
        An empty description would fall back to the tooltip, which only
        repeats the name."""
        hints = {"grid": "Show covers in a grid", "list": "Show a compact list"}
        for m, btn in self._view_buttons.items():
            btn.setAccessibleDescription(
                "Current view" if m == self._view_mode else hints[m])

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
        # Issue #396: opened from the keyboard, the card has focus. A
        # status change rebuilds the cards, so focus goes back to the new
        # card for the same manga afterwards (or into the page if it is
        # gone) instead of being lost with the old one.
        from_keyboard = any(card.hasFocus() for _m, card in self._cards)
        items = [
            ("Check Updates", lambda: self._ctx_check(manga)),
            ("Download All", lambda: self._ctx_download_all(manga)),
            (None, None),
            *[(f"Set: {status_label(status)}", self._status_setter(manga, status))
              for status in STATUS_ORDER],
            (None, None),
            ("Remove", lambda: self._ctx_remove(manga)),
        ]
        ContextMenu(self, x, y, items)
        if from_keyboard:
            # Rebuilt cards are shown only by events the rebuild posted;
            # a queued call runs after them.
            self._refocus_due.emit(manga.get("title") or "")

    @Slot(str)
    def _refocus_card(self, title):
        if not self.isVisible():
            return  # the action left the page (Check Updates, Download All)
        card = next((c for m, c in self._cards if m.get("title") == title),
                    None)
        if card is not None and card.isVisible():
            card.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            focus_into(self)  # the manga was removed or filtered out

    def _ctx_check(self, manga):
        self.app.worker.check_updates(
            [manga], self.app.app_state, self.app.config, force=True,
        )
        self.app.show_page("downloads")

    def _ctx_download_all(self, manga):
        # Issue #15: don't wipe the `downloaded` list — that's what was
        # causing already-on-disk (already read) chapters to be queued
        # again. We only reset `last_chapter` so check_for_updates returns
        # the full chapter list, then the queue step in DownloadsPage
        # skips anything `is_chapter_downloaded` already covers.
        title = manga.get("title", "")
        self.app.app_state.set_last_chapter(title, None)
        self.app.worker.check_updates(
            [manga], self.app.app_state, self.app.config,
            force=True, queue_all=True,
        )
        self.app.show_page("downloads")

    def _status_setter(self, manga, status):
        """A menu callback that takes no arguments. (A lambda with the
        status as a default argument would receive the menu action's
        "checked" flag in its place.)"""
        return lambda: self._ctx_set_status(manga, status)

    def _ctx_set_status(self, manga, status):
        for m in self.app.config.get("manga", []):
            if m.get("title") == manga.get("title"):
                m["status"] = status
                break
        self.app.config.save()
        self._refresh()

    def _ctx_remove(self, manga):
        title = manga.get("title", "")
        RemoveMangaModal(
            self, title,
            on_confirm=lambda purge: self._do_remove(title, purge_history=purge),
        ).exec()

    def _do_remove(self, title, purge_history=False):
        remove_manga(self.app, title, purge_history=purge_history)
        self._refresh()
        Toast(self, removed_message(title, purge_history), kind="success")

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
        """A cover finished downloading: show it on the cards that use
        it. The grid used to be rebuilt for this, once per batch of
        covers, which made a new library flicker while its covers
        arrived."""
        data = data or {}
        url = data.get("url")
        if not url or data.get("error") or not self.isVisible():
            return
        cache = self.app.cover_cache
        for manga, card in self._cards:
            if manga.get("cover_url") != url:
                continue
            if self._view_mode == "grid":
                cover = self._card_cover(url)
                if cover is not None:
                    card.update_cover(cover)
            else:
                card.update_cover(cache.get_cover(url, size=(36, 48)))
        for manga, card in self._continue_cards:
            if manga.get("cover_url") == url:
                card.update_cover(cache.get_cover(url, size=(48, 68)))

    def _on_check_done(self):
        if not self.isVisible() or self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(300, self._run_pending_refresh)

    def _run_pending_refresh(self):
        self._refresh_pending = False
        if self.isVisible():
            self._refresh()
