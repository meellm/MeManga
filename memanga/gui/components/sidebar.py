"""
Sidebar navigation component.
Fixed left panel with icon + label nav buttons, notification bell, and theme toggle.
"""

import customtkinter as ctk
from ..theme import (
    SIDEBAR_WIDTH, PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XXL, FONT_SIZE_XS,
    font, get_palette,
)


NAV_ITEMS = [
    ("dashboard", "Dashboard",  "\u25a3"),
    ("library",   "Library",    "\u2588\u2588"),
    ("add",       "Add Manga",  "+"),
    ("search",    "Search",     "\u26b2"),
    ("downloads", "Downloads",  "\u2913"),
    ("history",   "History",    "\u29d6"),
    ("settings",  "Settings",   "\u2699"),
    ("sources",   "Sources",    "\u2630"),
]


class Sidebar(ctk.CTkFrame):
    """Left sidebar with navigation buttons, notification bell, and theme toggle."""

    def __init__(self, parent, app):
        self.app = app
        palette = get_palette(ctk.get_appearance_mode().lower())

        super().__init__(
            parent,
            width=SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=palette["bg_sidebar"],
        )
        self.pack_propagate(False)

        self._buttons: dict[str, ctk.CTkButton] = {}
        self._active_page: str = ""

        self._build(palette)

        # Subscribe to notification events for badge updates
        self.app.events.subscribe("notification_added", lambda d: self._update_badge())

    def _build(self, palette):
        # Logo / title
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=PAD_LG, pady=(PAD_XL, PAD_SM))

        ctk.CTkLabel(
            title_frame,
            text="MeManga",
            font=font(FONT_SIZE_XXL, "bold"),
            text_color=palette["accent"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Manga Downloader",
            font=font(FONT_SIZE_SM),
            text_color=palette["fg_muted"],
        ).pack(anchor="w")

        # Divider
        ctk.CTkFrame(self, height=1, fg_color=palette["border"]).pack(
            fill="x", padx=PAD_LG, pady=(PAD_SM, PAD_MD),
        )

        # Nav buttons
        nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        nav_frame.pack(fill="both", expand=True, padx=PAD_SM)

        for page_name, label, icon in NAV_ITEMS:
            btn = ctk.CTkButton(
                nav_frame,
                text=f"  {icon}  {label}",
                font=font(FONT_SIZE_MD),
                anchor="w",
                height=38,
                corner_radius=8,
                fg_color="transparent",
                hover_color=palette["bg_card"],
                text_color=palette["fg_secondary"],
                command=lambda p=page_name: self.app.show_page(p),
            )
            btn.pack(fill="x", pady=1)
            self._buttons[page_name] = btn

        # Bottom section
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=PAD_SM, pady=PAD_LG, side="bottom")

        # Notification bell
        bell_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        bell_frame.pack(fill="x", pady=(0, PAD_SM))

        self._bell_btn = ctk.CTkButton(
            bell_frame,
            text="  \u2709  Notifications",
            font=font(FONT_SIZE_SM),
            anchor="w",
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color=palette["bg_card"],
            text_color=palette["fg_muted"],
            command=self._show_notifications,
        )
        self._bell_btn.pack(side="left", fill="x", expand=True)

        self._badge_label = ctk.CTkLabel(
            bell_frame, text="", font=font(FONT_SIZE_XS, "bold"),
            text_color="#ffffff", fg_color=palette["error"],
            corner_radius=8, width=22, height=18,
        )
        # Badge hidden by default, shown when unread > 0

        # Theme toggle
        self._theme_btn = ctk.CTkButton(
            bottom,
            text=self._theme_label(),
            font=font(FONT_SIZE_SM),
            anchor="w",
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color=palette["bg_card"],
            text_color=palette["fg_muted"],
            command=self._toggle_theme,
        )
        self._theme_btn.pack(fill="x")

        self._update_badge()

    def _theme_label(self) -> str:
        mode = ctk.get_appearance_mode().lower()
        icon = "\u263e" if mode == "dark" else "\u2600"
        label = "Dark Mode" if mode == "dark" else "Light Mode"
        return f"  {icon}  {label}"

    def _toggle_theme(self):
        current = ctk.get_appearance_mode().lower()
        new_mode = "light" if current == "dark" else "dark"
        ctk.set_appearance_mode(new_mode)
        self._theme_btn.configure(text=self._theme_label())
        self.app.on_theme_changed()

    def _show_notifications(self):
        from .notification import NotificationPanel
        NotificationPanel(self, self.app)
        self.app.app_state.mark_notifications_read()
        self._update_badge()

    def _update_badge(self):
        """Update notification badge count."""
        try:
            if not self.winfo_exists():
                return
            count = self.app.app_state.get_unread_count()
            if count > 0:
                self._badge_label.configure(text=str(min(count, 99)))
                self._badge_label.place(relx=1.0, x=-30, y=6)
            else:
                self._badge_label.place_forget()
        except Exception:
            pass

    def set_active(self, page_name: str):
        """Highlight the active navigation button."""
        palette = get_palette(ctk.get_appearance_mode().lower())
        for name, btn in self._buttons.items():
            if name == page_name:
                btn.configure(
                    fg_color=palette["accent"],
                    text_color="#ffffff",
                    hover_color=palette["accent_hover"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=palette["fg_secondary"],
                    hover_color=palette["bg_card"],
                )
        self._active_page = page_name

    def refresh_colors(self):
        """Update colors after theme change."""
        palette = get_palette(ctk.get_appearance_mode().lower())
        self.configure(fg_color=palette["bg_sidebar"])
        self.set_active(self._active_page)
        self._theme_btn.configure(
            text=self._theme_label(),
            text_color=palette["fg_muted"],
            hover_color=palette["bg_card"],
        )
