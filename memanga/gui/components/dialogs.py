"""
Modal dialog components.
"""

import customtkinter as ctk
from ..theme import font, FONT_SIZE_MD, FONT_SIZE_LG, PAD_MD, PAD_LG, PAD_XL, get_palette


class ConfirmDialog(ctk.CTkToplevel):
    """Simple yes/no confirmation dialog."""

    def __init__(self, parent, title: str, message: str, on_confirm=None, on_cancel=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x180")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

        palette = get_palette(ctk.get_appearance_mode().lower())

        # Center content
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=PAD_XL, pady=PAD_XL)

        ctk.CTkLabel(
            frame, text=message, font=font(FONT_SIZE_MD),
            wraplength=340, justify="center",
        ).pack(pady=(0, PAD_XL))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack()

        ctk.CTkButton(
            btn_frame, text="Cancel", width=100,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"], command=self._cancel,
        ).pack(side="left", padx=PAD_MD)

        ctk.CTkButton(
            btn_frame, text="Confirm", width=100,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._confirm,
        ).pack(side="left", padx=PAD_MD)

    def _confirm(self):
        self.grab_release()
        self.destroy()
        if self._on_confirm:
            self._on_confirm()

    def _cancel(self):
        self.grab_release()
        self.destroy()
        if self._on_cancel:
            self._on_cancel()


class InputDialog(ctk.CTkToplevel):
    """Dialog with a text input field."""

    def __init__(self, parent, title: str, prompt: str, default: str = "", on_submit=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("450x180")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._on_submit = on_submit
        palette = get_palette(ctk.get_appearance_mode().lower())

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=PAD_XL, pady=PAD_XL)

        ctk.CTkLabel(frame, text=prompt, font=font(FONT_SIZE_MD)).pack(anchor="w")

        self._entry = ctk.CTkEntry(frame, font=font(FONT_SIZE_MD))
        self._entry.pack(fill="x", pady=(PAD_MD, PAD_LG))
        if default:
            self._entry.insert(0, default)
        self._entry.focus()
        self._entry.bind("<Return>", lambda e: self._submit())

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(anchor="e")

        ctk.CTkButton(
            btn_frame, text="Cancel", width=80,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"], command=self._cancel,
        ).pack(side="left", padx=PAD_MD)

        ctk.CTkButton(
            btn_frame, text="OK", width=80,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._submit,
        ).pack(side="left")

    def _submit(self):
        value = self._entry.get().strip()
        self.grab_release()
        self.destroy()
        if self._on_submit:
            self._on_submit(value)

    def _cancel(self):
        self.grab_release()
        self.destroy()
