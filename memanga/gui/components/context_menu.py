"""
Right-click context menu.
"""

from PySide6.QtWidgets import QMenu
from PySide6.QtCore import QPoint
from .. import theme as T


class ContextMenu:
    """Show a context menu at the given screen position."""

    def __init__(self, parent, x, y, items):
        menu = QMenu(parent)
        menu.setStyleSheet(
            f"QMenu {{ background: {T.BG_CARD}; border: 1px solid {T.BORDER}; border-radius: 6px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px; color: {T.FG}; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {T.BORDER}; }}"
            f"QMenu::separator {{ height: 1px; background: {T.BORDER}; margin: 4px 8px; }}"
        )

        for label, callback in items:
            if label is None:
                menu.addSeparator()
            else:
                action = menu.addAction(label)
                if "remove" in label.lower():
                    action.setProperty("class", "danger")
                if callback:
                    action.triggered.connect(callback)

        menu.exec(QPoint(x, y))
