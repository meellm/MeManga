"""
Non-blocking toast notification popup.
"""

import customtkinter as ctk
from ..theme import font, FONT_SIZE_SM, PAD_MD, PAD_LG, get_palette


class Toast(ctk.CTkFrame):
    """A temporary notification that appears at the top-right and auto-dismisses."""

    def __init__(self, parent, message: str, kind: str = "info", duration: int = 3000):
        palette = get_palette(ctk.get_appearance_mode().lower())
        color_map = {
            "info": palette["accent"],
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
        }
        bg = color_map.get(kind, palette["accent"])

        super().__init__(parent, fg_color=bg, corner_radius=8)
        self.place(relx=1.0, rely=0.0, anchor="ne", x=-PAD_LG, y=PAD_LG)

        ctk.CTkLabel(
            self,
            text=message,
            font=font(FONT_SIZE_SM),
            text_color="#ffffff",
            padx=PAD_LG,
            pady=PAD_MD,
        ).pack()

        self.after(duration, self._dismiss)

    def _dismiss(self):
        try:
            self.place_forget()
            self.destroy()
        except Exception:
            pass
