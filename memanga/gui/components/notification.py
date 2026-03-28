"""
Notification center - Slide-out panel showing persistent activity log.
"""

import customtkinter as ctk
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XS,
    font, get_palette,
)


class NotificationPanel(ctk.CTkToplevel):
    """Popup notification panel showing recent activity."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Notifications")
        self.geometry("380x500")
        self.resizable(False, True)
        self.transient(parent)

        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_LG, pady=(PAD_LG, PAD_SM))

        ctk.CTkLabel(
            header, text="Notifications",
            font=font(FONT_SIZE_LG, "bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header, text="Mark Read", width=90, height=26,
            font=font(FONT_SIZE_XS), corner_radius=4,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg_secondary"],
            command=self._mark_read,
        ).pack(side="right")

        # Scrollable list
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=PAD_MD, pady=(0, PAD_MD))

        notifications = self.app.app_state.get_notifications(50)

        if not notifications:
            ctk.CTkLabel(
                scroll, text="No notifications yet",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
            ).pack(pady=PAD_XL)
        else:
            for n in notifications:
                self._render_notification(scroll, n, palette)

    def _render_notification(self, parent, n, palette):
        ntype = n.get("type", "info")
        msg = n.get("message", "")
        ts = n.get("timestamp", "")
        is_read = n.get("read", False)

        if "T" in ts:
            date_part = ts.split("T")[0]
            time_part = ts.split("T")[1][:5]
            ts_display = f"{date_part} {time_part}"
        else:
            ts_display = ts

        type_icons = {"download": "\u2913", "check": "\u2714", "error": "\u2716", "kindle": "\u2709"}
        type_colors = {
            "download": palette["success"],
            "check": palette["accent"],
            "error": palette["error"],
            "kindle": "#8b5cf6",
        }
        icon = type_icons.get(ntype, "\u2022")
        color = type_colors.get(ntype, palette["fg_muted"])
        fg = palette["fg"] if not is_read else palette["fg_muted"]

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)

        ctk.CTkLabel(row, text=icon, font=font(FONT_SIZE_MD), text_color=color, width=24).pack(side="left")

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=PAD_SM)

        ctk.CTkLabel(info, text=msg, font=font(FONT_SIZE_SM), text_color=fg, anchor="w", wraplength=280).pack(fill="x")
        ctk.CTkLabel(info, text=ts_display, font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w").pack(fill="x")

    def _mark_read(self):
        self.app.app_state.mark_notifications_read()
        self.destroy()
