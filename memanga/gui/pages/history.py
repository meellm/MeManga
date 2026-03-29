"""
Download History page - Persistent log of all downloads.
"""

import customtkinter as ctk
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_XS,
    font, get_palette,
)


class HistoryPage(BasePage):
    """Searchable download history log."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._widgets = []
        self._build()

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        ctk.CTkLabel(
            header, text="Download History",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(side="left")

        self._count_label = ctk.CTkLabel(
            header, text="", font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
        )
        self._count_label.pack(side="right")

        # Filter
        self._filter_entry = ctk.CTkEntry(
            self, placeholder_text="Filter by manga title...",
            font=font(FONT_SIZE_SM), height=32, width=300,
        )
        self._filter_entry.pack(anchor="w", padx=PAD_XL, pady=(0, PAD_MD))
        self._filter_entry.bind("<KeyRelease>", lambda e: self._render())

        # Column headers
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="x", padx=PAD_XL, pady=(0, PAD_SM))

        widths = [("Date", 100), ("Manga", 200), ("Chapter", 70), ("Format", 60), ("Size", 70), ("Kindle", 60)]
        for label, w in widths:
            ctk.CTkLabel(
                cols, text=label, font=font(FONT_SIZE_XS, "bold"),
                text_color=palette["fg_muted"], width=w, anchor="w",
            ).pack(side="left", padx=2)

        # Scrollable list
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_MD))

    def on_show(self, **kwargs):
        self._render()

    def _render(self):
        self._scroll.pack_forget()
        for w in self._widgets:
            w.destroy()
        self._widgets.clear()

        palette = get_palette(ctk.get_appearance_mode().lower())
        query = self._filter_entry.get().strip().lower()
        history = self.app.app_state.get_download_history(200)

        if query:
            history = [h for h in history if query in h.get("title", "").lower()]

        self._count_label.configure(text=f"{len(history)} entries")

        if not history:
            lbl = ctk.CTkLabel(
                self._scroll, text="No download history yet.",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
            )
            lbl.pack(pady=PAD_XL)
            self._widgets.append(lbl)
            self._scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_MD))
            return

        for h in history:
            row = ctk.CTkFrame(self._scroll, fg_color=palette["bg_card"], corner_radius=4, height=32)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            ts = h.get("timestamp", "")
            if "T" in ts:
                ts = ts.split("T")[0]

            ctk.CTkLabel(row, text=f"  {ts}", font=font(FONT_SIZE_XS), width=100, anchor="w").pack(side="left", padx=2)

            title = h.get("title", "")
            if len(title) > 25:
                title = title[:23] + ".."
            ctk.CTkLabel(row, text=title, font=font(FONT_SIZE_XS), width=200, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=f"Ch. {h.get('chapter', '?')}", font=font(FONT_SIZE_XS), width=70, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=h.get("format", "?"), font=font(FONT_SIZE_XS), width=60, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=f"{h.get('size_mb', 0):.1f}MB", font=font(FONT_SIZE_XS), width=70, anchor="w").pack(side="left", padx=2)

            kindle = "\u2714" if h.get("kindle_sent") else ""
            ctk.CTkLabel(row, text=kindle, font=font(FONT_SIZE_XS), width=60,
                         text_color=palette["success"]).pack(side="left", padx=2)

            self._widgets.append(row)

        self._scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_MD))
