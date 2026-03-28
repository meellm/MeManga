"""
Dashboard page - Stats overview, continue reading, recent activity.
"""

import customtkinter as ctk
from datetime import datetime
from pathlib import Path
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_XXL, FONT_SIZE_XS,
    font, get_palette,
)


class DashboardPage(BasePage):
    """Home dashboard with stats, continue reading, and activity."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._content = None
        self.app.events.subscribe("storage_calculated", self._on_storage)
        self.app.events.subscribe("check_complete", lambda d: self._rebuild_if_visible())
        self.app.events.subscribe("download_complete", lambda d: self._rebuild_if_visible())
        self._storage_size = None

    def on_show(self, **kwargs):
        self._rebuild()
        # Request storage calculation in background
        self.app.worker.calculate_storage(self.app.config.download_dir)

    def _rebuild_if_visible(self):
        """Debounced rebuild — wait 500ms to batch multiple events."""
        if not self.winfo_ismapped():
            return
        if hasattr(self, "_rebuild_timer"):
            self.after_cancel(self._rebuild_timer)
        self._rebuild_timer = self.after(500, self._rebuild)

    def _rebuild(self):
        if self._content:
            self._content.destroy()

        self._content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

        palette = get_palette(ctk.get_appearance_mode().lower())
        stats = self.app.state.get_stats()

        # Header
        ctk.CTkLabel(
            self._content, text="Dashboard",
            font=font(FONT_SIZE_XXL, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        # Stats cards row
        cards_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        cards_frame.pack(fill="x", padx=PAD_XL, pady=(0, PAD_XL))

        self._stat_card(cards_frame, "Manga Tracked", str(stats["total_manga"]), palette["accent"])
        self._stat_card(cards_frame, "Chapters Downloaded", str(stats["total_chapters"]), "#3b82f6")

        storage_text = f"{self._storage_size:.1f} MB" if self._storage_size else "..."
        self._stat_card(cards_frame, "Storage Used", storage_text, "#8b5cf6")

        last_check = stats.get("last_check")
        if last_check and "T" in last_check:
            check_display = last_check.split("T")[0]
        else:
            check_display = "Never"
        self._stat_card(cards_frame, "Last Check", check_display, "#f59e0b")

        # Continue Reading
        continue_data = self.app.state.get_continue_reading()
        if continue_data:
            ctk.CTkLabel(
                self._content, text="Continue Reading",
                font=font(FONT_SIZE_LG, "bold"),
            ).pack(anchor="w", padx=PAD_XL, pady=(0, PAD_SM))

            cr_frame = ctk.CTkFrame(self._content, fg_color=palette["bg_card"], corner_radius=10)
            cr_frame.pack(fill="x", padx=PAD_XL, pady=(0, PAD_XL))

            cr_inner = ctk.CTkFrame(cr_frame, fg_color="transparent")
            cr_inner.pack(fill="x", padx=PAD_LG, pady=PAD_MD)

            title = continue_data["title"]
            ch = continue_data.get("last_chapter", "?")
            last_read = continue_data.get("last_read", "")
            if last_read and "T" in last_read:
                last_read = last_read.split("T")[0]

            ctk.CTkLabel(
                cr_inner, text=title,
                font=font(FONT_SIZE_MD, "bold"), anchor="w",
            ).pack(fill="x")

            ctk.CTkLabel(
                cr_inner, text=f"Last read: Chapter {ch}  -  {last_read}",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"], anchor="w",
            ).pack(fill="x")

            ctk.CTkButton(
                cr_inner, text=f"Continue Ch. {ch}", height=32, width=140,
                font=font(FONT_SIZE_SM, "bold"), corner_radius=6,
                fg_color=palette["accent"], hover_color=palette["accent_hover"],
                command=lambda t=title, c=ch: self._continue_reading(t, c),
            ).pack(anchor="w", pady=(PAD_SM, 0))

        # Recent Activity
        notifications = self.app.state.get_notifications(10)
        ctk.CTkLabel(
            self._content, text="Recent Activity",
            font=font(FONT_SIZE_LG, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(0, PAD_SM))

        if notifications:
            for n in notifications:
                ntype = n.get("type", "info")
                msg = n.get("message", "")
                ts = n.get("timestamp", "")
                if "T" in ts:
                    ts = ts.split("T")[1][:5]

                type_colors = {
                    "download": palette["success"],
                    "check": palette["accent"],
                    "error": palette["error"],
                    "kindle": "#8b5cf6",
                }
                dot_color = type_colors.get(ntype, palette["fg_muted"])

                row = ctk.CTkFrame(self._content, fg_color="transparent", height=28)
                row.pack(fill="x", padx=PAD_XL, pady=1)
                row.pack_propagate(False)

                ctk.CTkLabel(
                    row, text="\u2022", font=font(FONT_SIZE_MD),
                    text_color=dot_color, width=20,
                ).pack(side="left")

                ctk.CTkLabel(
                    row, text=msg, font=font(FONT_SIZE_SM),
                    text_color=palette["fg"], anchor="w",
                ).pack(side="left", fill="x", expand=True)

                ctk.CTkLabel(
                    row, text=ts, font=font(FONT_SIZE_XS),
                    text_color=palette["fg_muted"],
                ).pack(side="right")
        else:
            ctk.CTkLabel(
                self._content, text="No activity yet. Check for updates to get started.",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
            ).pack(anchor="w", padx=PAD_XL, pady=PAD_MD)

        # Check History (mini chart)
        history = self.app.state.get_check_history(14)
        if history:
            ctk.CTkLabel(
                self._content, text="Check History (last 14)",
                font=font(FONT_SIZE_LG, "bold"),
            ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_SM))

            chart = ctk.CTkFrame(self._content, fg_color=palette["bg_card"], corner_radius=10, height=80)
            chart.pack(fill="x", padx=PAD_XL, pady=(0, PAD_XL))
            chart.pack_propagate(False)

            bar_frame = ctk.CTkFrame(chart, fg_color="transparent")
            bar_frame.pack(fill="both", expand=True, padx=PAD_MD, pady=PAD_SM)

            max_val = max((h.get("new_chapters", 0) for h in history), default=1) or 1
            for h in history:
                val = h.get("new_chapters", 0)
                bar_h = max(4, int(50 * val / max_val))

                col = ctk.CTkFrame(bar_frame, fg_color="transparent", width=16)
                col.pack(side="left", fill="y", expand=True, padx=1)
                col.pack_propagate(False)

                # Spacer + bar
                ctk.CTkFrame(col, fg_color="transparent").pack(fill="both", expand=True)
                bar_color = palette["accent"] if val > 0 else palette["border"]
                ctk.CTkFrame(col, fg_color=bar_color, height=bar_h, corner_radius=2).pack(
                    fill="x", side="bottom",
                )

    def _stat_card(self, parent, label, value, color):
        palette = get_palette(ctk.get_appearance_mode().lower())
        card = ctk.CTkFrame(parent, fg_color=palette["bg_card"], corner_radius=10, height=90)
        card.pack(side="left", fill="x", expand=True, padx=(0, PAD_SM))
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=PAD_LG, pady=PAD_MD)

        ctk.CTkLabel(
            inner, text=label, font=font(FONT_SIZE_XS),
            text_color=palette["fg_muted"], anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            inner, text=value, font=font(FONT_SIZE_XL, "bold"),
            text_color=color, anchor="w",
        ).pack(fill="x")

    def _continue_reading(self, title, chapter):
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == title:
                self.app.show_page("reader", manga=m, chapter=chapter)
                return

    def _on_storage(self, data):
        self._storage_size = data.get("total_mb", 0)
        if self.winfo_ismapped():
            self._rebuild()
