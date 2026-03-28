"""
Search result row widget.
"""

import customtkinter as ctk
from ..theme import font, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XS, PAD_SM, PAD_MD, get_palette


class SearchResultRow(ctk.CTkFrame):
    """A single search result entry."""

    def __init__(self, parent, result: dict, on_add=None):
        palette = get_palette(ctk.get_appearance_mode().lower())
        super().__init__(parent, fg_color=palette["bg_card"], corner_radius=8, height=56)
        self.pack_propagate(False)
        self._result = result

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=PAD_MD, pady=PAD_SM)

        # Left: title + source
        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            info, text=result.get("title", "Unknown"),
            font=font(FONT_SIZE_MD, "bold"), anchor="w",
        ).pack(fill="x")

        source_text = result.get("source", "")
        url = result.get("url", "")
        ctk.CTkLabel(
            info, text=f"{source_text}  -  {url[:50]}",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
        ).pack(fill="x")

        # Add button
        if on_add:
            ctk.CTkButton(
                inner, text="+ Add", width=70, height=30,
                font=font(FONT_SIZE_SM), corner_radius=6,
                fg_color=palette["accent"], hover_color=palette["accent_hover"],
                command=lambda: on_add(result),
            ).pack(side="right", padx=(PAD_SM, 0))
