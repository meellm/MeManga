"""
Keyboard handling shared by custom-painted click targets (issue #396).

Cards, rows and theme previews are QFrames, not buttons, so Qt gives them
no keyboard behaviour. These helpers give them what a push button has:
Enter, Return and Space activate it, and the Menu key or Shift+F10 opens
its context menu.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget

_ACTIVATE_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
_PLAIN = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)


def is_activation(event: QKeyEvent) -> bool:
    """Enter, Return or Space without Ctrl, Alt, Shift or Meta."""
    return event.key() in _ACTIVATE_KEYS and event.modifiers() in _PLAIN


def is_context_menu(event: QKeyEvent) -> bool:
    """The Menu key, or Shift+F10 (the Windows and Linux convention)."""
    if event.key() == Qt.Key.Key_Menu:
        return True
    return (event.key() == Qt.Key.Key_F10
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier)


def menu_anchor(widget: QWidget) -> QPoint:
    """Global position for a menu opened from the keyboard: the widget's
    centre, since there is no pointer position to use."""
    return widget.mapToGlobal(widget.rect().center())
