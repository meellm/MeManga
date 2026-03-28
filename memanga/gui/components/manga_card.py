"""
Manga cover art card for grid view with badge support and selection.
"""

import customtkinter as ctk
from ..theme import (
    CARD_WIDTH, CARD_HEIGHT, CARD_COVER_HEIGHT, CARD_RADIUS,
    PAD_XS, PAD_SM, FONT_SIZE_SM, FONT_SIZE_XS,
    STATUS_COLORS, font, get_palette,
)


class MangaCard(ctk.CTkFrame):
    """A card showing cover art, title, status badge, and optional NEW indicator."""

    def __init__(self, parent, manga: dict, cover_image, on_click=None,
                 on_right_click=None, new_count: int = 0, selectable: bool = False,
                 selected: bool = False, on_select=None):
        palette = get_palette(ctk.get_appearance_mode().lower())
        super().__init__(
            parent,
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
            corner_radius=CARD_RADIUS,
            fg_color=palette["bg_card"],
            cursor="hand2",
        )
        self.pack_propagate(False)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click
        self._selected = selected

        # Selection checkbox (hidden by default)
        if selectable:
            self._check_var = ctk.BooleanVar(value=selected)
            self._checkbox = ctk.CTkCheckBox(
                self, text="", variable=self._check_var, width=24, height=24,
                command=lambda: on_select(manga, self._check_var.get()) if on_select else None,
            )
            self._checkbox.place(x=6, y=6)

        # Cover image
        self._cover_label = ctk.CTkLabel(
            self, text="", image=cover_image,
            width=CARD_WIDTH, height=CARD_COVER_HEIGHT,
        )
        self._cover_label.pack(fill="x")

        # NEW badge overlay
        if new_count > 0:
            badge = ctk.CTkLabel(
                self, text=f" {new_count} NEW ",
                font=font(FONT_SIZE_XS, "bold"),
                text_color="#ffffff", fg_color="#22c55e",
                corner_radius=4, height=18,
            )
            badge.place(relx=1.0, x=-8, y=8, anchor="ne")

        # Info section
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(fill="both", expand=True, padx=PAD_SM, pady=PAD_XS)

        # Title (truncated)
        title = manga.get("title", "Unknown")
        if len(title) > 22:
            title = title[:20] + ".."
        ctk.CTkLabel(
            info, text=title, font=font(FONT_SIZE_SM, "bold"),
            text_color=palette["fg"], anchor="w",
        ).pack(fill="x")

        # Status + reading progress
        status = manga.get("status", "reading")
        status_color = STATUS_COLORS.get(status, palette["fg_muted"])

        bottom = ctk.CTkFrame(info, fg_color="transparent")
        bottom.pack(fill="x")

        ctk.CTkLabel(
            bottom, text=status.capitalize(),
            font=font(FONT_SIZE_XS), text_color=status_color, anchor="w",
        ).pack(side="left")

        # Bind clicks
        self.bind("<Button-1>", self._clicked)
        self._cover_label.bind("<Button-1>", self._clicked)
        for child in info.winfo_children():
            child.bind("<Button-1>", self._clicked)

        # Right-click (bind to all children so it works anywhere on the card)
        if on_right_click:
            for widget in [self, self._cover_label] + list(info.winfo_children()) + list(bottom.winfo_children()):
                widget.bind("<Button-2>", self._right_clicked)
                widget.bind("<Button-3>", self._right_clicked)

    def _clicked(self, event=None):
        if self._on_click:
            self._on_click(self._manga)

    def _right_clicked(self, event=None):
        if self._on_right_click and event:
            self._on_right_click(self._manga, event.x_root, event.y_root)

    def update_cover(self, cover_image):
        self._cover_label.configure(image=cover_image)
