"""
Base page class for all GUI pages.
"""

from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    """Base class for all pages. Subclass and override on_show/on_hide."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

    def on_show(self, **kwargs):
        pass

    def on_hide(self):
        pass
