"""
Search page - Search across multiple manga sources.
"""

import customtkinter as ctk
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XL,
    font, get_palette,
)
from ..components.search_result import SearchResultRow
from ..components.toast import Toast


# Top sources for quick search
DEFAULT_SEARCH_SOURCES = [
    "mangadex.org",
    "bato.to",
    "mangapill.com",
    "comick.io",
    "mangakakalot.com",
]


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
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        ctk.CTkLabel(
            self, text="Search",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        # Search bar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_XL, pady=(0, PAD_LG))

        self._search_entry = ctk.CTkEntry(
            bar, placeholder_text="Search for manga...",
            font=font(FONT_SIZE_MD), height=40,
        )
        self._search_entry.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))
        self._search_entry.bind("<Return>", lambda e: self._do_search())

        self._search_btn = ctk.CTkButton(
            bar, text="Search", width=100, height=40,
            font=font(FONT_SIZE_MD, "bold"),
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._do_search,
        )
        self._search_btn.pack(side="right")

        # Status
        self._status_label = ctk.CTkLabel(
            self, text="", font=font(FONT_SIZE_SM),
            text_color=palette["fg_muted"],
        )
        self._status_label.pack(anchor="w", padx=PAD_XL)

        # Results area
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(PAD_SM, PAD_MD))

    def _do_search(self):
        query = self._search_entry.get().strip()
        if not query:
            return

        # Clear old results
        for w in self._result_widgets:
            w.destroy()
        self._result_widgets.clear()
        self._results.clear()

        self.app.worker.search_manga(query, DEFAULT_SEARCH_SOURCES)

    def _on_started(self, data):
        self._status_label.configure(text=f"Searching for '{data['query']}'...")
        self._search_btn.configure(state="disabled")

    def _on_result(self, data):
        self._results.append(data)
        row = SearchResultRow(self._scroll, result=data, on_add=self._add_result)
        row.pack(fill="x", pady=2)
        self._result_widgets.append(row)
        self._status_label.configure(text=f"{len(self._results)} results found...")

    def _on_complete(self, data):
        self._search_btn.configure(state="normal")
        count = len(self._results)
        if count == 0:
            self._status_label.configure(text="No results found. Try a different query or source.")
        else:
            self._status_label.configure(text=f"{count} results found")

    def _add_result(self, result):
        """Navigate to Add Manga page with prefilled data."""
        self.app.show_page("add", prefill={
            "title": result.get("title", ""),
            "url": result.get("url", ""),
        })
