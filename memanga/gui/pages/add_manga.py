"""
Add Manga page - Form to add a new manga to tracking.
"""

import customtkinter as ctk
from urllib.parse import urlparse
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    font, get_palette,
)
from ..components.toast import Toast


class AddMangaPage(BasePage):
    """Form to add a new manga."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._prefill = None
        self._build()

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        ctk.CTkLabel(
            self, text="Add Manga",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        # Form container
        form = ctk.CTkFrame(self, fg_color=palette["bg_card"], corner_radius=12)
        form.pack(fill="x", padx=PAD_XL, pady=(0, PAD_LG))

        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=PAD_XL, pady=PAD_XL)

        # Title
        ctk.CTkLabel(inner, text="Manga Title", font=font(FONT_SIZE_SM, "bold")).pack(anchor="w")
        self._title_entry = ctk.CTkEntry(
            inner, placeholder_text="e.g. One Piece", font=font(FONT_SIZE_MD), height=36,
        )
        self._title_entry.pack(fill="x", pady=(PAD_SM, PAD_LG))

        # Primary URL
        ctk.CTkLabel(inner, text="Primary Source URL", font=font(FONT_SIZE_SM, "bold")).pack(anchor="w")
        self._url_entry = ctk.CTkEntry(
            inner, placeholder_text="https://mangadex.org/title/...", font=font(FONT_SIZE_MD), height=36,
        )
        self._url_entry.pack(fill="x", pady=(PAD_SM, PAD_SM))

        self._source_label = ctk.CTkLabel(
            inner, text="", font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
        )
        self._source_label.pack(anchor="w", pady=(0, PAD_LG))
        self._url_entry.bind("<KeyRelease>", self._on_url_change)

        # Backup source toggle
        self._backup_var = ctk.BooleanVar(value=False)
        self._backup_check = ctk.CTkCheckBox(
            inner, text="Add backup source",
            font=font(FONT_SIZE_SM), variable=self._backup_var,
            command=self._toggle_backup,
        )
        self._backup_check.pack(anchor="w", pady=(0, PAD_SM))

        self._backup_frame = ctk.CTkFrame(inner, fg_color="transparent")

        ctk.CTkLabel(self._backup_frame, text="Backup Source URL", font=font(FONT_SIZE_SM, "bold")).pack(anchor="w")
        self._backup_url_entry = ctk.CTkEntry(
            self._backup_frame, placeholder_text="https://...", font=font(FONT_SIZE_MD), height=36,
        )
        self._backup_url_entry.pack(fill="x", pady=(PAD_SM, PAD_SM))

        delay_row = ctk.CTkFrame(self._backup_frame, fg_color="transparent")
        delay_row.pack(fill="x", pady=(0, PAD_SM))
        ctk.CTkLabel(delay_row, text="Fallback delay (days):", font=font(FONT_SIZE_SM)).pack(side="left")
        self._delay_entry = ctk.CTkEntry(delay_row, width=60, font=font(FONT_SIZE_SM), height=28)
        self._delay_entry.pack(side="left", padx=PAD_SM)
        self._delay_entry.insert(0, "2")

        # Add button
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(PAD_LG, 0))

        ctk.CTkButton(
            btn_frame, text="Add Manga", height=40, font=font(FONT_SIZE_MD, "bold"),
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._add_manga,
        ).pack(side="right")

    def on_show(self, **kwargs):
        prefill = kwargs.get("prefill")
        if prefill:
            self._title_entry.delete(0, "end")
            self._title_entry.insert(0, prefill.get("title", ""))
            self._url_entry.delete(0, "end")
            self._url_entry.insert(0, prefill.get("url", ""))
            self._on_url_change()

    def _toggle_backup(self):
        if self._backup_var.get():
            self._backup_frame.pack(fill="x", pady=(0, PAD_SM))
        else:
            self._backup_frame.pack_forget()

    def _on_url_change(self, event=None):
        url = self._url_entry.get().strip()
        if url:
            try:
                domain = urlparse(url).netloc.replace("www.", "")
                from ...downloader import get_supported_sources
                sources = get_supported_sources()
                if domain in sources:
                    self._source_label.configure(
                        text=f"Source detected: {domain}",
                        text_color=get_palette(ctk.get_appearance_mode().lower())["success"],
                    )
                else:
                    self._source_label.configure(
                        text=f"Unknown source: {domain}",
                        text_color=get_palette(ctk.get_appearance_mode().lower())["warning"],
                    )
            except Exception:
                self._source_label.configure(text="")
        else:
            self._source_label.configure(text="")

    def _add_manga(self):
        title = self._title_entry.get().strip()
        url = self._url_entry.get().strip()

        if not title or not url:
            Toast(self, "Title and URL are required", kind="error")
            return

        # Check for duplicates
        existing = self.app.config.get("manga", [])
        for m in existing:
            if m.get("title", "").lower() == title.lower():
                Toast(self, f"'{title}' already exists", kind="warning")
                return

        # Parse source
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            Toast(self, "Invalid URL", kind="error")
            return

        # Build entry
        if self._backup_var.get() and self._backup_url_entry.get().strip():
            backup_url = self._backup_url_entry.get().strip()
            backup_domain = urlparse(backup_url).netloc.replace("www.", "")
            try:
                delay = int(self._delay_entry.get().strip())
            except ValueError:
                delay = 2

            entry = {
                "title": title,
                "fallback_delay_days": delay,
                "sources": [
                    {"url": url, "source": domain},
                    {"url": backup_url, "source": backup_domain},
                ],
            }
        else:
            entry = {
                "title": title,
                "source": domain,
                "url": url,
            }

        existing.append(entry)
        self.app.config.set("manga", existing)
        self.app.config.save()

        # Try to fetch cover in background (don't block UI)
        def _fetch_cover():
            try:
                from ...scrapers import get_scraper
                scraper = get_scraper(domain)
                if hasattr(scraper, "get_cover_url"):
                    cover = scraper.get_cover_url(url)
                    if cover:
                        # Update the manga entry with cover URL
                        manga_list = self.app.config.get("manga", [])
                        for m in manga_list:
                            if m.get("title") == title:
                                m["cover_url"] = cover
                                break
                        self.app.config.save()
            except Exception:
                pass

        import threading
        threading.Thread(target=_fetch_cover, daemon=True).start()

        # Clear form
        self._title_entry.delete(0, "end")
        self._url_entry.delete(0, "end")
        self._source_label.configure(text="")
        self._backup_url_entry.delete(0, "end")
        self._backup_var.set(False)
        self._backup_frame.pack_forget()

        Toast(self, f"Added '{title}'", kind="success")
