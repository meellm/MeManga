"""
Downloads page - Active/completed downloads with progress bars.
"""

import subprocess
import sys
import customtkinter as ctk
from pathlib import Path
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    font, get_palette,
)
from ..components.progress_item import ProgressItem
from ..components.toast import Toast


class DownloadsPage(BasePage):
    """Downloads view with progress tracking."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._active_items: dict[str, ProgressItem] = {}
        self._completed_items: list = []
        self._build()

        # Subscribe to download events
        self.app.events.subscribe("download_started", self._on_started)
        self.app.events.subscribe("download_progress", self._on_progress)
        self.app.events.subscribe("download_complete", self._on_complete)
        self.app.events.subscribe("download_error", self._on_error)
        self.app.events.subscribe("download_queued", self._on_queued)
        self.app.events.subscribe("download_cancelled", self._on_cancelled)
        self.app.events.subscribe("check_complete", self._on_check_complete)

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        ctk.CTkLabel(
            self, text="Downloads",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        # Active downloads
        ctk.CTkLabel(
            self, text="Active",
            font=font(FONT_SIZE_LG, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(0, PAD_SM))

        self._active_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", height=250)
        self._active_frame.pack(fill="x", padx=PAD_XL, pady=(0, PAD_LG))

        self._empty_label = ctk.CTkLabel(
            self._active_frame, text="No active downloads",
            font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
        )
        self._empty_label.pack(pady=PAD_LG)

        # Completed downloads
        ctk.CTkLabel(
            self, text="Completed",
            font=font(FONT_SIZE_LG, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(0, PAD_SM))

        self._completed_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._completed_frame.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_MD))

    def _hide_empty(self):
        try:
            if self._active_items:
                self._empty_label.pack_forget()
            else:
                self._empty_label.pack(pady=PAD_LG)
        except Exception:
            pass

    def _on_started(self, data):
        task_id = data["task_id"]
        if task_id in self._active_items:
            return

        item = ProgressItem(
            self._active_frame,
            task_id=task_id,
            title=data["title"],
            chapter=str(data["chapter"]),
            on_cancel=self._cancel_download,
        )
        item.pack(fill="x", pady=2)
        self._active_items[task_id] = item
        self._hide_empty()

    def _on_queued(self, data):
        task_id = data["task_id"]
        if task_id in self._active_items:
            return
        item = ProgressItem(
            self._active_frame,
            task_id=task_id,
            title=data["title"],
            chapter=str(data["chapter"]),
            on_cancel=self._cancel_download,
        )
        item.pack(fill="x", pady=2)
        self._active_items[task_id] = item
        self._hide_empty()

    def _on_progress(self, data):
        task_id = data["task_id"]
        item = self._active_items.get(task_id)
        if item:
            item.update_progress(data["current"], data["total"])

    def _on_complete(self, data):
        task_id = data["task_id"]
        item = self._active_items.get(task_id)
        if item:
            item.set_complete(data.get("path"))
            self.after(2000, lambda tid=task_id, d=data: self._move_to_completed(tid, d))

        Toast(self, f"Downloaded {data.get('title', '')} Ch. {data.get('chapter', '')}", kind="success")

    def _on_error(self, data):
        task_id = data["task_id"]
        item = self._active_items.get(task_id)
        if item:
            item.set_error(data.get("error", "Unknown error"))
        Toast(self, f"Failed: {data.get('title', '')} Ch. {data.get('chapter', '')}", kind="error")

    def _on_cancelled(self, data):
        task_id = data["task_id"]
        item = self._active_items.pop(task_id, None)
        if item:
            try:
                item.destroy()
            except Exception:
                pass
        self._hide_empty()

    def _cancel_download(self, task_id):
        self.app.worker.cancel_download(task_id)

    def _move_to_completed(self, task_id, data):
        if not self.winfo_exists():
            return
        item = self._active_items.pop(task_id, None)
        if item:
            try:
                item.destroy()
            except Exception:
                pass

        palette = get_palette(ctk.get_appearance_mode().lower())
        row = ctk.CTkFrame(self._completed_frame, fg_color=palette["bg_card"], corner_radius=6, height=36)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)

        label = f"{data.get('title', '')} - Ch. {data.get('chapter', '')}"
        ctk.CTkLabel(row, text=f"  {label}", font=font(FONT_SIZE_SM), anchor="w").pack(
            side="left", fill="x", expand=True,
        )

        path = data.get("path")
        if path:
            ctk.CTkButton(
                row, text="Open Folder", width=90, height=26,
                font=font(FONT_SIZE_SM - 1), corner_radius=4,
                fg_color=palette["bg_secondary"], hover_color=palette["border"],
                text_color=palette["fg"],
                command=lambda p=path: self._open_folder(p),
            ).pack(side="right", padx=PAD_SM)

        self._completed_items.append(row)
        self._hide_empty()

    def _open_folder(self, path):
        try:
            folder = str(Path(path).parent)
            if sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            Toast(self, "Could not open folder", kind="error")

    def _on_check_complete(self, data):
        """Auto-queue downloads when check finds new chapters."""
        results = data.get("results", [])
        if not results:
            Toast(self, "No new chapters found", kind="info")
            return

        total = sum(len(r["chapters"]) for r in results)
        Toast(self, f"Found {total} new chapter(s), downloading...", kind="success")

        # Build global kindle config once
        global_kindle = self.app.config.delivery_mode == "email" and self.app.config.email_enabled
        naming_template = self.app.config.get("delivery.naming_template")

        for r in results:
            manga = r["manga"]
            for ch in r["chapters"]:
                output_dir = self.app.config.download_dir
                output_format = self.app.config.output_format

                # Per-manga kindle toggle: only send if global is on AND manga hasn't opted out
                kindle_cfg = None
                if global_kindle and manga.get("send_to_kindle", True):
                    from ...config import get_app_password
                    kindle_cfg = {
                        "kindle_email": self.app.config.get("email.kindle_email"),
                        "sender_email": self.app.config.get("email.sender_email"),
                        "app_password": get_app_password(self.app.config),
                        "smtp_server": self.app.config.get("email.smtp_server", "smtp.gmail.com"),
                        "smtp_port": self.app.config.get("email.smtp_port", 587),
                    }

                self.app.worker.download_chapter(
                    manga=manga, chapter=ch,
                    output_dir=output_dir, output_format=output_format,
                    state=self.app.app_state, kindle_cfg=kindle_cfg,
                    naming_template=naming_template,
                )
