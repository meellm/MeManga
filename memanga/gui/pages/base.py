"""
Base page class for all GUI pages.
"""

import customtkinter as ctk


class BasePage(ctk.CTkFrame):
    """Base class for all pages. Subclass and override on_show/on_hide."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

    def on_show(self, **kwargs):
        """Called when this page becomes visible. Override to refresh data."""
        pass

    def on_hide(self):
        """Called when this page is hidden. Override to clean up."""
        pass
