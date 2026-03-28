"""
Detail page - Manga info, edit, chapters, download from chapter, and actions.
"""

import customtkinter as ctk
from pathlib import Path
from urllib.parse import urlparse
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_XS,
    STATUS_COLORS, font, get_palette,
)
from ..components.toast import Toast
from ..components.dialogs import ConfirmDialog, InputDialog


class DetailPage(BasePage):
    """Manga detail view with info, edit, chapters, and actions."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._content_frame = None
        self._editing = False

    def on_show(self, **kwargs):
        manga = kwargs.get("manga")
        if manga:
            self._manga = manga
        self._editing = False
        if self._manga:
            self._rebuild()

    def _get_source_display(self, manga):
        """Extract primary and backup source domains from manga config."""
        sources = manga.get("sources", [])
        if sources:
            primary = sources[0].get("source", sources[0].get("url", ""))
            backup = sources[1].get("source", "") if len(sources) > 1 else ""
            primary_url = sources[0].get("url", "")
            backup_url = sources[1].get("url", "") if len(sources) > 1 else ""
        else:
            primary = manga.get("source", "")
            primary_url = manga.get("url", "")
            backup = ""
            backup_url = ""
        return primary, primary_url, backup, backup_url

    def _rebuild(self):
        if self._content_frame:
            self._content_frame.destroy()

        self._content_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)

        palette = get_palette(ctk.get_appearance_mode().lower())
        manga = self._manga
        title = manga.get("title", "Unknown")
        state_data = self.app.app_state.get_manga_state(title)
        primary, primary_url, backup, backup_url = self._get_source_display(manga)

        # Back button
        back_frame = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        back_frame.pack(fill="x", padx=PAD_XL, pady=(PAD_LG, PAD_SM))

        ctk.CTkButton(
            back_frame, text="< Back to Library", width=140, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color="transparent", hover_color=palette["bg_card"],
            text_color=palette["fg_secondary"],
            command=lambda: self.app.show_page("library"),
        ).pack(side="left")

        # Main layout: cover left + info right
        main = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        main.pack(fill="x", padx=PAD_XL, pady=PAD_MD)

        # Left: cover
        cover_url = manga.get("cover_url")
        cover_img = self.app.cover_cache.get_cover(cover_url, size=(200, 280))
        ctk.CTkLabel(main, text="", image=cover_img).pack(side="left", anchor="n", padx=(0, PAD_XL))

        # Right: info
        info = ctk.CTkFrame(main, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, anchor="n")

        # Title
        ctk.CTkLabel(
            info, text=title, font=font(FONT_SIZE_XL, "bold"), anchor="w",
        ).pack(fill="x")

        # Source info
        ctk.CTkLabel(
            info, text=f"Primary: {primary}",
            font=font(FONT_SIZE_SM), text_color=palette["fg_muted"], anchor="w",
        ).pack(fill="x", pady=(PAD_SM, 0))

        if primary_url:
            ctk.CTkLabel(
                info, text=f"  {primary_url}",
                font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
            ).pack(fill="x")

        if backup:
            ctk.CTkLabel(
                info, text=f"Backup: {backup}",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"], anchor="w",
            ).pack(fill="x", pady=(PAD_SM, 0))
            if backup_url:
                ctk.CTkLabel(
                    info, text=f"  {backup_url}",
                    font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
                ).pack(fill="x")

            delay = manga.get("fallback_delay_days", 2)
            ctk.CTkLabel(
                info, text=f"Fallback delay: {delay} days",
                font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
            ).pack(fill="x")

        # Status dropdown
        status = manga.get("status", "reading")
        status_frame = ctk.CTkFrame(info, fg_color="transparent")
        status_frame.pack(fill="x", pady=PAD_MD)

        ctk.CTkLabel(status_frame, text="Status:", font=font(FONT_SIZE_SM)).pack(side="left")
        self._status_menu = ctk.CTkOptionMenu(
            status_frame,
            values=["reading", "on-hold", "dropped", "completed"],
            font=font(FONT_SIZE_SM), height=28, width=130,
            command=self._on_status_change,
        )
        self._status_menu.set(status)
        self._status_menu.pack(side="left", padx=PAD_SM)

        # Kindle toggle (per-manga, respects global setting)
        global_email_on = (self.app.config.delivery_mode == "email" and self.app.config.email_enabled)
        manga_kindle = manga.get("send_to_kindle", True)

        kindle_frame = ctk.CTkFrame(info, fg_color="transparent")
        kindle_frame.pack(fill="x", pady=(0, PAD_SM))

        self._kindle_var = ctk.BooleanVar(value=manga_kindle and global_email_on)
        self._kindle_check = ctk.CTkCheckBox(
            kindle_frame, text="Send to Kindle after download",
            font=font(FONT_SIZE_SM), variable=self._kindle_var,
            command=self._on_kindle_toggle,
        )
        self._kindle_check.pack(side="left")

        if not global_email_on:
            self._kindle_check.configure(state="disabled")
            ctk.CTkLabel(
                kindle_frame, text="  (enable email in Settings first)",
                font=font(FONT_SIZE_XS), text_color=palette["fg_muted"],
            ).pack(side="left")

        # Stats
        downloaded = state_data.get("downloaded", [])
        last_ch = state_data.get("last_chapter") or "-"
        last_updated = state_data.get("last_updated") or "Never"
        if last_updated != "Never" and "T" in last_updated:
            last_updated = last_updated.split("T")[0]

        stats_text = f"Downloaded: {len(downloaded)} chapters  |  Last: Ch. {last_ch}  |  Updated: {last_updated}"
        ctk.CTkLabel(
            info, text=stats_text,
            font=font(FONT_SIZE_SM), text_color=palette["fg_secondary"], anchor="w",
        ).pack(fill="x", pady=(0, PAD_MD))

        # Action buttons - row 1
        actions1 = ctk.CTkFrame(info, fg_color="transparent")
        actions1.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkButton(
            actions1, text="Check Updates", height=34, width=130,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._check_updates,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            actions1, text="Download From...", height=34, width=140,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._download_from_chapter,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            actions1, text="Download All", height=34, width=120,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._download_all,
        ).pack(side="left")

        # Action buttons - row 2
        actions2 = ctk.CTkFrame(info, fg_color="transparent")
        actions2.pack(fill="x", pady=(0, PAD_LG))

        ctk.CTkButton(
            actions2, text="Edit Manga", height=34, width=110,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._show_edit_form,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            actions2, text="Remove", height=34, width=100,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["error"], hover_color="#b91c1c",
            command=self._confirm_remove,
        ).pack(side="left")

        # Edit form (hidden by default)
        self._edit_frame = ctk.CTkFrame(self._content_frame, fg_color=palette["bg_card"], corner_radius=10)

        edit_inner = ctk.CTkFrame(self._edit_frame, fg_color="transparent")
        edit_inner.pack(fill="x", padx=PAD_LG, pady=PAD_LG)

        ctk.CTkLabel(edit_inner, text="Edit Manga", font=font(FONT_SIZE_LG, "bold")).pack(anchor="w")

        ctk.CTkLabel(edit_inner, text="Title:", font=font(FONT_SIZE_SM)).pack(anchor="w", pady=(PAD_MD, 0))
        self._edit_title = ctk.CTkEntry(edit_inner, font=font(FONT_SIZE_SM), height=32)
        self._edit_title.pack(fill="x", pady=(PAD_XS, 0))
        self._edit_title.insert(0, title)

        ctk.CTkLabel(edit_inner, text="Primary URL:", font=font(FONT_SIZE_SM)).pack(anchor="w", pady=(PAD_MD, 0))
        self._edit_url = ctk.CTkEntry(edit_inner, font=font(FONT_SIZE_SM), height=32)
        self._edit_url.pack(fill="x", pady=(PAD_XS, 0))
        self._edit_url.insert(0, primary_url)

        ctk.CTkLabel(edit_inner, text="Backup URL (leave empty to remove):", font=font(FONT_SIZE_SM)).pack(anchor="w", pady=(PAD_MD, 0))
        self._edit_backup = ctk.CTkEntry(edit_inner, font=font(FONT_SIZE_SM), height=32)
        self._edit_backup.pack(fill="x", pady=(PAD_XS, 0))
        self._edit_backup.insert(0, backup_url)

        edit_btns = ctk.CTkFrame(edit_inner, fg_color="transparent")
        edit_btns.pack(fill="x", pady=(PAD_LG, 0))

        ctk.CTkButton(
            edit_btns, text="Save Changes", height=34, width=120,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._save_edit,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            edit_btns, text="Cancel", height=34, width=80,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._hide_edit_form,
        ).pack(side="left")

        # Chapter list section
        ch_header = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        ch_header.pack(fill="x", padx=PAD_XL, pady=(PAD_MD, PAD_SM))

        ctk.CTkLabel(
            ch_header, text=f"Downloaded Chapters ({len(downloaded)})",
            font=font(FONT_SIZE_LG, "bold"), anchor="w",
        ).pack(side="left")

        if downloaded:
            for ch_num in reversed(downloaded):
                ch_frame = ctk.CTkFrame(
                    self._content_frame, fg_color=palette["bg_card"],
                    corner_radius=6, height=40,
                )
                ch_frame.pack(fill="x", padx=PAD_XL, pady=1)
                ch_frame.pack_propagate(False)

                ctk.CTkLabel(
                    ch_frame, text=f"  Chapter {ch_num}",
                    font=font(FONT_SIZE_SM), anchor="w",
                ).pack(side="left", fill="x", expand=True)

                ctk.CTkButton(
                    ch_frame, text="Read", width=60, height=26,
                    font=font(FONT_SIZE_XS), corner_radius=4,
                    fg_color=palette["accent"], hover_color=palette["accent_hover"],
                    command=lambda c=ch_num: self._read_chapter(c),
                ).pack(side="right", padx=PAD_SM)
        else:
            ctk.CTkLabel(
                self._content_frame,
                text="No chapters downloaded yet. Use 'Check Updates' or 'Download From...' to start.",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
            ).pack(anchor="w", padx=PAD_XL, pady=PAD_SM)

    # ---- Status ----

    def _on_kindle_toggle(self):
        """Toggle per-manga kindle delivery."""
        if not self._manga:
            return
        val = self._kindle_var.get()
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["send_to_kindle"] = val
                self._manga = m
                break
        self.app.config.save()
        kind = "info" if val else "warning"
        msg = "Kindle delivery enabled" if val else "Kindle delivery disabled"
        Toast(self._content_frame, msg, kind=kind)

    def _on_status_change(self, new_status):
        if not self._manga:
            return
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["status"] = new_status
                self._manga = m
                break
        self.app.config.save()
        Toast(self._content_frame, f"Status: {new_status}", kind="info")

    # ---- Edit ----

    def _show_edit_form(self):
        if not self._editing:
            self._edit_frame.pack(fill="x", padx=PAD_XL, pady=PAD_MD)
            self._editing = True

    def _hide_edit_form(self):
        self._edit_frame.pack_forget()
        self._editing = False

    def _save_edit(self):
        if not self._manga:
            return

        new_title = self._edit_title.get().strip()
        new_url = self._edit_url.get().strip()
        new_backup = self._edit_backup.get().strip()
        old_title = self._manga.get("title", "")

        if not new_title:
            Toast(self._content_frame, "Title cannot be empty", kind="error")
            return

        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == old_title:
                # Update title
                m["title"] = new_title

                # Update URLs - handle both single and multi-source formats
                if new_url:
                    new_domain = urlparse(new_url).netloc.replace("www.", "")
                    if new_backup:
                        backup_domain = urlparse(new_backup).netloc.replace("www.", "")
                        m.pop("source", None)
                        m.pop("url", None)
                        m["sources"] = [
                            {"url": new_url, "source": new_domain},
                            {"url": new_backup, "source": backup_domain},
                        ]
                    elif "sources" in m:
                        m["sources"][0] = {"url": new_url, "source": new_domain}
                        if not new_backup and len(m.get("sources", [])) > 1:
                            m["sources"] = [m["sources"][0]]
                    else:
                        m["source"] = new_domain
                        m["url"] = new_url

                # Rename state if title changed
                if new_title != old_title:
                    old_state = self.app.app_state.get_manga_state(old_title)
                    if old_state:
                        self.app.app_state._data.setdefault("manga", {})[new_title] = old_state
                        self.app.app_state.remove_manga(old_title)

                self._manga = m
                break

        self.app.config.save()
        self._editing = False
        Toast(self._content_frame, "Manga updated", kind="success")
        self._rebuild()

    # ---- Downloads ----

    def _check_updates(self):
        if self._manga:
            self.app.worker.check_updates([self._manga], self.app.app_state, self.app.config)
            self.app.show_page("downloads")
            Toast(self, "Checking for updates...", kind="info")

    def _download_from_chapter(self):
        """Prompt for a chapter number and download from there."""
        if not self._manga:
            return
        InputDialog(
            self, title="Download From Chapter",
            prompt="Enter chapter number to start from (0 for all):",
            default="1",
            on_submit=self._do_download_from,
        )

    def _do_download_from(self, value):
        if not value:
            return
        try:
            from_ch = float(value)
        except ValueError:
            Toast(self._content_frame, "Invalid chapter number", kind="error")
            return

        title = self._manga.get("title", "")
        self.app.app_state.reset_manga_progress(title, from_ch)

        self.app.worker.check_updates([self._manga], self.app.app_state, self.app.config)
        self.app.show_page("downloads")
        Toast(self, f"Downloading from chapter {int(from_ch) if from_ch == int(from_ch) else from_ch}...", kind="info")

    def _download_all(self):
        self._do_download_from("0")

    # ---- Remove ----

    def _confirm_remove(self):
        if not self._manga:
            return
        title = self._manga.get("title", "Unknown")
        ConfirmDialog(
            self, title="Remove Manga",
            message=f"Remove '{title}' from your library?\nThis also removes download history.",
            on_confirm=self._do_remove,
        )

    def _do_remove(self):
        title = self._manga.get("title", "")
        manga_list = self.app.config.get("manga", [])
        manga_list = [m for m in manga_list if m.get("title") != title]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self.app.app_state.remove_manga(title)
        self.app.show_page("library")

    # ---- Reader ----

    def _read_chapter(self, chapter_num):
        self.app.show_page("reader", manga=self._manga, chapter=chapter_num)
