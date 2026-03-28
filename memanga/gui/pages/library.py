"""
Library page - Grid/List view with sorting, right-click menus, and bulk operations.
"""

import customtkinter as ctk
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    CARD_WIDTH, CARD_HEIGHT, STATUS_COLORS,
    font, get_palette,
)
from ..components.manga_card import MangaCard
from ..components.manga_row import MangaRow
from ..components.context_menu import ContextMenu
from ..components.toast import Toast
from ..components.dialogs import ConfirmDialog


class LibraryPage(BasePage):
    """Main library view with grid/list toggle, sorting, right-click, and bulk ops."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._view_mode = "grid"
        self._filter_status = "all"
        self._search_query = ""
        self._sort_by = self.app.config.get("gui.sort_by", "title")
        self._cards: list = []
        self._select_mode = False
        self._selected_titles: set = set()

        self._build()

        self.app.events.subscribe("cover_loaded", self._on_cover_loaded)
        self.app.events.subscribe("check_complete", lambda d: self._on_check_done())
        self.app.events.subscribe("download_complete", lambda d: self._on_check_done())

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_XL, pady=(PAD_XL, PAD_MD))

        ctk.CTkLabel(
            header, text="Library",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(side="left")

        # Right side controls
        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="right")

        # Check All button
        ctk.CTkButton(
            controls, text="Check Updates", width=120, height=32,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._check_all,
        ).pack(side="right", padx=(PAD_SM, 0))

        # Select mode toggle
        self._select_btn = ctk.CTkButton(
            controls, text="Select", width=70, height=32,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._toggle_select_mode,
        )
        self._select_btn.pack(side="right", padx=(PAD_SM, PAD_SM))

        # View toggle
        self._toggle_btn = ctk.CTkSegmentedButton(
            controls, values=["Grid", "List"], width=120,
            font=font(FONT_SIZE_SM),
            command=self._on_view_toggle,
        )
        self._toggle_btn.set("Grid")
        self._toggle_btn.pack(side="right", padx=(PAD_SM, 0))

        # Filter bar
        filter_bar = ctk.CTkFrame(self, fg_color="transparent")
        filter_bar.pack(fill="x", padx=PAD_XL, pady=(0, PAD_MD))

        self._search_entry = ctk.CTkEntry(
            filter_bar, placeholder_text="Filter manga...",
            font=font(FONT_SIZE_SM), height=32, width=200,
        )
        self._search_entry.pack(side="left")
        self._search_entry.bind("<KeyRelease>", self._on_search)

        self._status_filter = ctk.CTkOptionMenu(
            filter_bar,
            values=["All", "Reading", "On-hold", "Dropped", "Completed"],
            font=font(FONT_SIZE_SM), height=32, width=110,
            command=self._on_status_filter,
        )
        self._status_filter.pack(side="left", padx=PAD_SM)

        # Sort dropdown
        self._sort_menu = ctk.CTkOptionMenu(
            filter_bar,
            values=["Title A-Z", "Last Updated", "Recently Added", "Chapter Count", "Status"],
            font=font(FONT_SIZE_SM), height=32, width=140,
            command=self._on_sort_change,
        )
        sort_display = {"title": "Title A-Z", "last_updated": "Last Updated",
                        "recently_added": "Recently Added", "chapter_count": "Chapter Count",
                        "status": "Status"}
        self._sort_menu.set(sort_display.get(self._sort_by, "Title A-Z"))
        self._sort_menu.pack(side="left", padx=PAD_SM)

        self._count_label = ctk.CTkLabel(
            filter_bar, text="", font=font(FONT_SIZE_SM),
            text_color=palette["fg_muted"],
        )
        self._count_label.pack(side="right")

        # Scrollable content area
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_SM))

        # Grid container — pack with fill="x" only so height comes from configure()
        # (place()-managed children don't propagate height to pack)
        self._grid_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._grid_frame.pack(fill="x")

        # Bulk action bar (hidden by default)
        self._bulk_bar = ctk.CTkFrame(self, fg_color=palette["bg_card"], corner_radius=8, height=46)
        self._bulk_count = ctk.CTkLabel(self._bulk_bar, text="0 selected", font=font(FONT_SIZE_SM, "bold"))
        self._bulk_count.pack(side="left", padx=PAD_LG)

        ctk.CTkButton(
            self._bulk_bar, text="Check All", width=90, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._bulk_check,
        ).pack(side="left", padx=PAD_SM)

        ctk.CTkButton(
            self._bulk_bar, text="Set Reading", width=100, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=lambda: self._bulk_set_status("reading"),
        ).pack(side="left", padx=PAD_SM)

        ctk.CTkButton(
            self._bulk_bar, text="Remove", width=80, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["error"], hover_color="#b91c1c",
            command=self._bulk_remove,
        ).pack(side="left", padx=PAD_SM)

        self._scroll.bind("<Configure>", self._on_resize)

    def on_show(self, **kwargs):
        self._refresh()

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

        # Sort (cache state lookups to avoid O(n * state_access) per sort)
        sort_key = self._sort_by
        if sort_key == "title":
            results.sort(key=lambda m: m.get("title", "").lower())
        elif sort_key in ("last_updated", "recently_added", "chapter_count"):
            state_cache = {
                m.get("title", ""): self.app.app_state.get_manga_state(m.get("title", ""))
                for m in results
            }
            if sort_key == "last_updated":
                results.sort(key=lambda m: state_cache.get(m.get("title", ""), {}).get("last_updated") or "", reverse=True)
            elif sort_key == "recently_added":
                results.sort(key=lambda m: state_cache.get(m.get("title", ""), {}).get("created") or "", reverse=True)
            elif sort_key == "chapter_count":
                results.sort(key=lambda m: len(state_cache.get(m.get("title", ""), {}).get("downloaded", [])), reverse=True)
        elif sort_key == "status":
            order = {"reading": 0, "on-hold": 1, "completed": 2, "dropped": 3}
            results.sort(key=lambda m: order.get(m.get("status", "reading"), 4))

        return results

    def _refresh(self):
        for widget in self._grid_frame.winfo_children():
            widget.destroy()
        self._cards.clear()

        manga_list = self._get_filtered_manga()
        palette = get_palette(ctk.get_appearance_mode().lower())
        self._count_label.configure(text=f"{len(manga_list)} manga")

        if not manga_list:
            empty_frame = ctk.CTkFrame(self._grid_frame, fg_color="transparent")
            empty_frame.pack(expand=True, pady=80)

            ctk.CTkLabel(
                empty_frame, text="No manga tracked yet",
                font=font(FONT_SIZE_LG), text_color=palette["fg_muted"], justify="center",
            ).pack()

            ctk.CTkButton(
                empty_frame, text="+ Add Manga", height=36, width=150,
                font=font(FONT_SIZE_MD), corner_radius=8,
                fg_color=palette["accent"], hover_color=palette["accent_hover"],
                command=lambda: self.app.show_page("add"),
            ).pack(pady=PAD_LG)
            return

        if self._view_mode == "grid":
            self._build_grid(manga_list)
        else:
            self._build_list(manga_list)

    def _build_grid(self, manga_list):
        for manga in manga_list:
            cover_url = manga.get("cover_url")
            cover_img = self.app.cover_cache.get_cover(cover_url, size=(180, 230))
            title = manga.get("title", "")
            new_count = self.app.app_state.get_new_chapters(title)

            card = MangaCard(
                self._grid_frame, manga=manga, cover_image=cover_img,
                on_click=self._on_manga_click,
                on_right_click=self._on_right_click,
                new_count=new_count,
                selectable=self._select_mode,
                selected=title in self._selected_titles,
                on_select=self._on_select_toggle,
            )
            self._cards.append((manga, card))

        # Defer reflow so the scroll frame has a real width from layout
        self.after(50, self._reflow_grid)

    def _build_list(self, manga_list):
        for manga in manga_list:
            title = manga.get("title", "")
            state_data = self.app.app_state.get_manga_state(title)
            cover_url = manga.get("cover_url")
            thumb = self.app.cover_cache.get_cover(cover_url, size=(40, 55)) if cover_url else None
            new_count = self.app.app_state.get_new_chapters(title)

            row = MangaRow(
                self._grid_frame, manga=manga, state_data=state_data,
                cover_image=thumb, on_click=self._on_manga_click,
                on_right_click=self._on_right_click,
                new_count=new_count,
                selectable=self._select_mode,
                selected=title in self._selected_titles,
                on_select=self._on_select_toggle,
            )
            row.pack(fill="x", pady=2)
            self._cards.append((manga, row))

    def _reflow_grid(self):
        if self._view_mode != "grid" or not self._cards:
            return
        try:
            available_width = self._scroll.winfo_width() - 20
        except Exception:
            available_width = 800
        if available_width < 200:
            available_width = 800

        card_spacing = 12
        cols = max(1, available_width // (CARD_WIDTH + card_spacing))

        for i, (manga, card) in enumerate(self._cards):
            row = i // cols
            col = i % cols
            card.place(
                x=col * (CARD_WIDTH + card_spacing),
                y=row * (CARD_HEIGHT + card_spacing),
                width=CARD_WIDTH, height=CARD_HEIGHT,
            )

        total_rows = (len(self._cards) + cols - 1) // cols
        self._grid_frame.configure(height=total_rows * (CARD_HEIGHT + card_spacing) + card_spacing)

    def _on_resize(self, event=None):
        if self._view_mode != "grid" or not self._cards:
            return
        # Debounce resize — only reflow after 150ms of no resize events
        if hasattr(self, "_resize_timer"):
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(150, self._reflow_grid)

    def _on_view_toggle(self, value):
        self._view_mode = value.lower()
        self._refresh()

    def _on_search(self, event=None):
        self._search_query = self._search_entry.get().strip()
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

    # ---- Right-Click Context Menu ----

    def _on_right_click(self, manga, x, y):
        title = manga.get("title", "")
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
        title = manga.get("title", "")
        self.app.app_state.reset_manga_progress(title, from_chapter=0)
        self.app.worker.check_updates([manga], self.app.app_state, self.app.config)
        self.app.show_page("downloads")

    def _ctx_set_status(self, manga, status):
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == manga.get("title"):
                m["status"] = status
                break
        self.app.config.save()
        self._refresh()
        Toast(self, f"Status: {status}", kind="info")

    def _ctx_remove(self, manga):
        title = manga.get("title", "Unknown")
        ConfirmDialog(
            self, title="Remove", message=f"Remove '{title}'?",
            on_confirm=lambda: self._do_remove(title),
        )

    def _do_remove(self, title):
        manga_list = [m for m in self.app.config.get("manga", []) if m.get("title") != title]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self.app.app_state.remove_manga(title)
        self._refresh()

    # ---- Bulk Operations ----

    def _toggle_select_mode(self):
        self._select_mode = not self._select_mode
        palette = get_palette(ctk.get_appearance_mode().lower())
        if self._select_mode:
            self._select_btn.configure(fg_color=palette["accent"], text_color="#ffffff")
            self._bulk_bar.pack(fill="x", padx=PAD_XL, pady=(0, PAD_SM))
        else:
            self._select_btn.configure(fg_color=palette["bg_secondary"], text_color=palette["fg"])
            self._bulk_bar.pack_forget()
            self._selected_titles.clear()
        self._refresh()

    def _on_select_toggle(self, manga, selected):
        title = manga.get("title", "")
        if selected:
            self._selected_titles.add(title)
        else:
            self._selected_titles.discard(title)
        self._bulk_count.configure(text=f"{len(self._selected_titles)} selected")

    def _bulk_check(self):
        manga_list = [m for m in self.app.config.get("manga", [])
                      if m.get("title") in self._selected_titles]
        if manga_list:
            self.app.worker.check_updates(manga_list, self.app.app_state, self.app.config)
            self.app.show_page("downloads")

    def _bulk_set_status(self, status):
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") in self._selected_titles:
                m["status"] = status
        self.app.config.save()
        self._refresh()
        Toast(self, f"Set {len(self._selected_titles)} manga to {status}", kind="success")

    def _bulk_remove(self):
        count = len(self._selected_titles)
        ConfirmDialog(
            self, title="Bulk Remove",
            message=f"Remove {count} manga from library?",
            on_confirm=self._do_bulk_remove,
        )

    def _do_bulk_remove(self):
        for title in self._selected_titles:
            self.app.app_state.remove_manga(title)
        manga_list = [m for m in self.app.config.get("manga", [])
                      if m.get("title") not in self._selected_titles]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self._selected_titles.clear()
        self._refresh()

    # ---- Cover / Check callbacks ----

    def _on_cover_loaded(self, data):
        if not hasattr(self, "_cover_refresh_pending") or not self._cover_refresh_pending:
            self._cover_refresh_pending = True
            self.after(500, self._debounced_cover_refresh)

    def _debounced_cover_refresh(self):
        self._cover_refresh_pending = False
        if self.winfo_ismapped():
            self._refresh()

    def _on_check_done(self):
        if self.winfo_ismapped():
            self.after(300, self._refresh)

    def _check_all(self):
        manga_list = self.app.config.get("manga", [])
        if manga_list:
            self.app.worker.check_updates(manga_list, self.app.app_state, self.app.config)
            Toast(self, "Checking for updates...", kind="info")
        else:
            Toast(self, "No manga to check", kind="info")
