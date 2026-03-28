"""
Sources page - Browseable list of supported manga sources + user's active sources.
"""

import customtkinter as ctk
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XL, FONT_SIZE_XS, FONT_SIZE_LG,
    font, get_palette,
)


class SourcesPage(BasePage):
    """List of supported sources and user's active manga sources."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._all_sources = []
        self._widgets = []
        self._build()

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(PAD_XL, PAD_MD))
        self._scroll = scroll

        # Section 1: User's active sources
        ctk.CTkLabel(
            scroll, text="Your Active Sources",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(anchor="w", pady=(0, PAD_SM))

        ctk.CTkLabel(
            scroll, text="Sources currently used by your tracked manga",
            font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
        ).pack(anchor="w", pady=(0, PAD_MD))

        self._user_sources_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._user_sources_frame.pack(fill="x", pady=(0, PAD_XL))

        # Divider
        ctk.CTkFrame(scroll, height=1, fg_color=palette["border"]).pack(fill="x", pady=PAD_MD)

        # Section 2: All supported sources
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", pady=(PAD_MD, PAD_SM))

        ctk.CTkLabel(
            header, text="All Supported Sources",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(side="left")

        self._count_label = ctk.CTkLabel(
            header, text="",
            font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
        )
        self._count_label.pack(side="right")

        # Filter
        self._filter_entry = ctk.CTkEntry(
            scroll, placeholder_text="Filter sources...",
            font=font(FONT_SIZE_SM), height=32, width=300,
        )
        self._filter_entry.pack(anchor="w", pady=(0, PAD_MD))
        self._filter_entry.bind("<KeyRelease>", self._on_filter)

        # Source list container
        self._source_list_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._source_list_frame.pack(fill="x")

    def on_show(self, **kwargs):
        if not self._all_sources:
            self._load_sources()
        self._render_user_sources()
        self._render_all_sources()

    def _load_sources(self):
        try:
            from ...downloader import get_supported_sources
            self._all_sources = sorted(get_supported_sources())
        except Exception:
            self._all_sources = []

    def _render_user_sources(self):
        """Show sources used by tracked manga."""
        for w in self._user_sources_frame.winfo_children():
            w.destroy()

        palette = get_palette(ctk.get_appearance_mode().lower())
        manga_list = self.app.config.get("manga", [])

        # Collect unique sources with their manga titles
        source_manga = {}
        for m in manga_list:
            title = m.get("title", "Unknown")
            sources = m.get("sources", [])
            if sources:
                for s in sources:
                    domain = s.get("source", "")
                    if domain:
                        source_manga.setdefault(domain, []).append(title)
            else:
                domain = m.get("source", "")
                if domain:
                    source_manga.setdefault(domain, []).append(title)

        if not source_manga:
            ctk.CTkLabel(
                self._user_sources_frame,
                text="No active sources. Add manga to see their sources here.",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"],
            ).pack(anchor="w")
            return

        all_health = self.app.app_state.get_all_source_health()

        for domain, titles in sorted(source_manga.items()):
            row = ctk.CTkFrame(self._user_sources_frame, fg_color=palette["bg_card"], corner_radius=6)
            row.pack(fill="x", pady=2)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=PAD_MD, pady=PAD_SM)

            # Domain + health dot
            domain_row = ctk.CTkFrame(inner, fg_color="transparent")
            domain_row.pack(fill="x")

            health = all_health.get(domain, {})
            health_status = health.get("status", "unknown")
            health_colors = {"ok": palette["success"], "warning": palette["warning"],
                             "error": palette["error"]}
            dot_color = health_colors.get(health_status, palette["fg_muted"])

            ctk.CTkLabel(
                domain_row, text="\u2022", font=font(FONT_SIZE_LG),
                text_color=dot_color, width=20,
            ).pack(side="left")

            ctk.CTkLabel(
                domain_row, text=domain,
                font=font(FONT_SIZE_MD, "bold"), anchor="w",
            ).pack(side="left")

            # Health info
            if health_status == "error":
                err_msg = health.get("last_error_msg", "")
                ctk.CTkLabel(
                    inner, text=f"Errors: {health.get('error_count', 0)} - {err_msg}",
                    font=font(FONT_SIZE_XS), text_color=palette["error"], anchor="w",
                ).pack(fill="x")

            manga_text = ", ".join(titles[:5])
            if len(titles) > 5:
                manga_text += f" +{len(titles) - 5} more"
            ctk.CTkLabel(
                inner, text=f"Used by: {manga_text}",
                font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], anchor="w",
            ).pack(fill="x")

    def _render_all_sources(self):
        for w in self._source_list_frame.winfo_children():
            w.destroy()
        self._widgets.clear()

        palette = get_palette(ctk.get_appearance_mode().lower())
        query = self._filter_entry.get().strip().lower()

        filtered = [s for s in self._all_sources if not query or query in s.lower()]
        self._count_label.configure(text=f"{len(filtered)} of {len(self._all_sources)} sources")

        for source in filtered:
            row = ctk.CTkFrame(self._source_list_frame, fg_color=palette["bg_card"], corner_radius=4, height=32)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(
                row, text=f"  {source}",
                font=font(FONT_SIZE_SM), anchor="w",
            ).pack(side="left", fill="x", expand=True)

            self._widgets.append(row)

    def _on_filter(self, event=None):
        self._render_all_sources()
