"""
Download progress bar widget.
"""

import customtkinter as ctk
from ..theme import font, FONT_SIZE_SM, FONT_SIZE_XS, PAD_SM, PAD_MD, get_palette


class ProgressItem(ctk.CTkFrame):
    """A single download progress entry."""

    def __init__(self, parent, task_id: str, title: str, chapter: str, on_cancel=None):
        palette = get_palette(ctk.get_appearance_mode().lower())
        super().__init__(parent, fg_color=palette["bg_card"], corner_radius=8)
        self.task_id = task_id
        self._on_cancel = on_cancel

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=PAD_MD, pady=PAD_SM)

        # Title row
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(
            top, text=f"{title} - Ch. {chapter}",
            font=font(FONT_SIZE_SM, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self._status_label = ctk.CTkLabel(
            top, text="Waiting...",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"],
        )
        self._status_label.pack(side="right")

        if on_cancel:
            ctk.CTkButton(
                top, text="x", width=24, height=24,
                font=font(FONT_SIZE_XS), corner_radius=4,
                fg_color="transparent", hover_color=palette["error"],
                text_color=palette["fg_muted"],
                command=lambda: on_cancel(task_id),
            ).pack(side="right", padx=(PAD_SM, 0))

        # Progress bar
        self._progress = ctk.CTkProgressBar(inner, height=6)
        self._progress.pack(fill="x", pady=(PAD_SM, 0))
        self._progress.set(0)

    def update_progress(self, current: int, total: int):
        """Update the progress bar and status text."""
        if total > 0:
            self._progress.set(current / total)
            self._status_label.configure(text=f"{current}/{total} pages")

    def set_complete(self, path: str = None):
        palette = get_palette(ctk.get_appearance_mode().lower())
        self._progress.set(1.0)
        self._status_label.configure(text="Complete", text_color=palette["success"])

    def set_error(self, error: str):
        palette = get_palette(ctk.get_appearance_mode().lower())
        self._status_label.configure(text=f"Error: {error[:40]}", text_color=palette["error"])
