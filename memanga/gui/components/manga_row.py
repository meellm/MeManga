"""
Manga row widget for list view with badge support and selection.
"""

import customtkinter as ctk
from ..theme import (
    PAD_SM, PAD_MD, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XS,
    STATUS_COLORS, font, get_palette,
)


class MangaRow(ctk.CTkFrame):
    """A single row in the list view showing manga info."""

    def __init__(self, parent, manga: dict, state_data: dict, cover_image=None,
                 on_click=None, on_right_click=None, new_count: int = 0,
                 selectable: bool = False, selected: bool = False, on_select=None):
        palette = get_palette(ctk.get_appearance_mode().lower())
        super().__init__(parent, fg_color=palette["bg_card"], corner_radius=6, height=60, cursor="hand2")
        self.pack_propagate(False)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click

        # Selection checkbox
        if selectable:
            self._check_var = ctk.BooleanVar(value=selected)
            ctk.CTkCheckBox(
                self, text="", variable=self._check_var, width=24, height=24,
                command=lambda: on_select(manga, self._check_var.get()) if on_select else None,
            ).pack(side="left", padx=(PAD_SM, 0))

        # Thumbnail
        if cover_image:
            ctk.CTkLabel(
                self, text="", image=cover_image, width=40, height=55,
            ).pack(side="left", padx=(PAD_SM, PAD_MD), pady=4)

        # Info column
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=4)

        title_frame = ctk.CTkFrame(info, fg_color="transparent")
        title_frame.pack(fill="x")

        ctk.CTkLabel(
            title_frame, text=manga.get("title", "Unknown"),
            font=font(FONT_SIZE_MD, "bold"), text_color=palette["fg"], anchor="w",
        ).pack(side="left")

        # NEW badge
        if new_count > 0:
            ctk.CTkLabel(
                title_frame, text=f" {new_count} NEW ",
                font=font(FONT_SIZE_XS, "bold"),
                text_color="#ffffff", fg_color="#22c55e",
                corner_radius=4, height=16,
            ).pack(side="left", padx=PAD_SM)

        # Source
        sources = manga.get("sources", [])
        source = sources[0].get("source", "") if sources else manga.get("source", "")
        ctk.CTkLabel(
            info, text=source,
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
        ).pack(fill="x")

        # Right side: status + chapters
        right = ctk.CTkFrame(self, fg_color="transparent", width=160)
        right.pack(side="right", padx=PAD_MD)
        right.pack_propagate(False)

        status = manga.get("status", "reading")
        status_color = STATUS_COLORS.get(status, palette["fg_muted"])
        ctk.CTkLabel(
            right, text=status.capitalize(),
            font=font(FONT_SIZE_SM), text_color=status_color, anchor="e",
        ).pack(fill="x")

        downloaded = state_data.get("downloaded", [])
        last_ch = state_data.get("last_chapter") or "-"
        ctk.CTkLabel(
            right, text=f"Ch. {last_ch}  |  {len(downloaded)} dl",
            font=font(FONT_SIZE_XS), text_color=palette["fg_secondary"], anchor="e",
        ).pack(fill="x")

        # Click bindings
        self.bind("<Button-1>", self._clicked)
        for child in self.winfo_children():
            child.bind("<Button-1>", self._clicked)

        if on_right_click:
            for widget in [self] + list(self.winfo_children()):
                widget.bind("<Button-2>", self._right_clicked)
                widget.bind("<Button-3>", self._right_clicked)

    def _clicked(self, event=None):
        if self._on_click:
            self._on_click(self._manga)

    def _right_clicked(self, event=None):
        if self._on_right_click and event:
            self._on_right_click(self._manga, event.x_root, event.y_root)
