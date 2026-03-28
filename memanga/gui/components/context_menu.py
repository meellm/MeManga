"""
Right-click context menu for manga cards/rows.
"""

import customtkinter as ctk
from ..theme import font, FONT_SIZE_SM, PAD_SM, PAD_MD, get_palette


class ContextMenu(ctk.CTkToplevel):
    """A popup context menu positioned at cursor."""

    def __init__(self, parent, x, y, items):
        """
        Args:
            parent: Parent widget
            x, y: Screen coordinates for menu position
            items: List of (label, callback) tuples. Use (None, None) for separator.
        """
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        palette = get_palette(ctk.get_appearance_mode().lower())
        self.configure(fg_color=palette["bg_card"])

        frame = ctk.CTkFrame(self, fg_color=palette["bg_card"], corner_radius=8,
                             border_width=1, border_color=palette["border"])
        frame.pack(fill="both", expand=True)

        for label, callback in items:
            if label is None:
                ctk.CTkFrame(frame, height=1, fg_color=palette["border"]).pack(fill="x", padx=PAD_SM)
                continue

            # Determine text color for destructive actions
            text_color = palette["error"] if "remove" in label.lower() else palette["fg"]

            btn = ctk.CTkButton(
                frame, text=f"  {label}", anchor="w",
                font=font(FONT_SIZE_SM), height=30,
                fg_color="transparent", hover_color=palette["bg_secondary"],
                text_color=text_color, corner_radius=4,
                command=lambda cb=callback: self._select(cb),
            )
            btn.pack(fill="x", padx=2, pady=1)

        self.geometry(f"+{x}+{y}")

        # Close on click outside
        self.bind("<FocusOut>", lambda e: self.destroy())
        self.after(100, lambda: self.focus_force())

    def _select(self, callback):
        self.destroy()
        if callback:
            callback()
