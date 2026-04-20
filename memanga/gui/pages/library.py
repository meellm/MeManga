"""
Library page — main home view with grid/list, filters, stats bar.
"""

from datetime import datetime
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QScrollArea, QWidget, QGridLayout, QFrame,
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
        # Refresh when something edits/adds/removes a manga elsewhere
        # (Add Manga dialog, Detail page, cover backfill writes a URL).
        self.app.events.subscribe("library_updated", lambda d: self._on_check_done())

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_SM)
        layout.setSpacing(T.PAD_SM)

        # Header row
        header = QHBoxLayout()

        title_block = QVBoxLayout()
        title = QLabel("Library")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        title_block.addWidget(title)

        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        title_block.addWidget(self._stats_label)
        header.addLayout(title_block)
        header.addStretch()

        add_btn = QPushButton("+ Add")
        add_btn.setProperty("class", "accent")
        add_btn.setFixedHeight(30)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._open_add_dialog)
        header.addWidget(add_btn)

        check_btn = QPushButton("Check All")
        check_btn.setProperty("class", "accent")
        check_btn.setFixedHeight(30)
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self._check_all)
        header.addWidget(check_btn)

        layout.addLayout(header)

        # Filter bar
        filter_bar = QHBoxLayout()

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Filter manga...")
        self._search_entry.setFixedHeight(30)
        self._search_entry.setMaximumWidth(200)
        self._search_entry.textChanged.connect(self._on_search)
        filter_bar.addWidget(self._search_entry)

        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "Reading", "On-hold", "Dropped", "Completed"])
        self._status_filter.setFixedHeight(30)
        self._status_filter.currentTextChanged.connect(self._on_status_filter)
        filter_bar.addWidget(self._status_filter)

        self._sort_menu = QComboBox()
        self._sort_menu.addItems(["Title A-Z", "Last Updated", "Recently Added", "Chapter Count", "Status"])
        self._sort_menu.setFixedHeight(30)
        sort_display = {"title": "Title A-Z", "last_updated": "Last Updated",
                        "recently_added": "Recently Added", "chapter_count": "Chapter Count",
                        "status": "Status"}
        self._sort_menu.setCurrentText(sort_display.get(self._sort_by, "Title A-Z"))
        self._sort_menu.currentTextChanged.connect(self._on_sort_change)
        filter_bar.addWidget(self._sort_menu)

        filter_bar.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        filter_bar.addWidget(self._count_label)

        layout.addLayout(filter_bar)

        # Scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._grid_layout = QGridLayout(self._scroll_content)
        self._grid_layout.setSpacing(T.PAD_MD)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

    def on_show(self, **kwargs):
        self._refresh()

    def _refresh(self):
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
        self._stats_label.setText(
            f"{stats['total_manga']} manga  \u00b7  {stats['total_chapters']} chapters  \u00b7  Last check: {check_text}"
        )
        self._count_label.setText(f"{len(manga_list)} shown")

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

            card = MangaCard(
                self._scroll_content, manga=manga, cover_image=cover_img,
                on_click=self._on_manga_click,
                on_right_click=self._on_right_click,
                new_count=new_count,
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

    def _on_search(self, text):
        self._search_query = text.strip()
        self._refresh()

    def _on_status_filter(self, value):
        self._filter_status = value.lower() if value != "All" else "all"
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
        self.app.app_state.reset_manga_progress(manga.get("title", ""), from_chapter=0)
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
