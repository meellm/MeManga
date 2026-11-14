"""
Floating toast notification.
"""

import weakref

from PySide6.QtWidgets import QLabel, QWidget
from PySide6.QtCore import QEvent, QTimer, Qt
from .. import theme as T

# Toast kind -> token of its fill. The text on it is always
# `accent.on_primary`, which the token table keeps readable on the accent
# and on every status colour in both themes (issue #395); white text was
# 1.9:1 on the dark theme's accent.
_FILL_TOKENS = {
    "info": "accent.primary",
    "success": "status.success",
    "warning": "status.warn",
    "warn": "status.warn",      # alias for callers using the shorter name
    "error": "status.danger",
}

_MAX_WIDTH = 420        # px; longer messages wrap
_GAP = 8                # px between stacked toasts
_MS_PER_CHAR = 60       # reading time added to the base duration
_MAX_DURATION = 12000   # ms

# parent widget -> toasts currently shown on it, oldest first. Weak keys:
# a closed page takes its entry with it.
_live = weakref.WeakKeyDictionary()


class Toast(QLabel):
    """Auto-dismissing toast shown at top-right of parent.

    Several toasts on the same parent stack downwards instead of
    covering each other, follow the parent when it is resized, and
    take the new colours when the theme is switched while they show.
    """

    def __init__(self, parent: QWidget, message: str, kind: str = "info", duration: int = 3000):
        super().__init__(message, parent)
        # Messages often quote error text from sites; show it literally.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._kind = kind
        self._apply_theme()
        # A toast can still be on screen when the theme is switched (the
        # Save that follows a switch in Settings shows one). Held weakly:
        # the subscription goes with the toast.
        T.on_theme_change(self._apply_theme)
        # The padding, as margins: the label's own size and
        # height-for-width maths include these.
        self.setContentsMargins(16, 8, 16, 8)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._parent_ref = weakref.ref(parent) if parent is not None else None
        self._fit(parent)

        self._announce(message)

        siblings = _live.setdefault(parent, []) if parent is not None else []
        siblings.append(self)
        if parent is not None:
            parent.installEventFilter(self)
        _restack(parent)
        self.raise_()
        self.show()

        # A long message needs longer to read than a short one. Callers
        # that ask for a longer time of their own keep it.
        if duration <= 3000:
            extra = max(0, len(message or "") - 40) * _MS_PER_CHAR
            duration = min(_MAX_DURATION, duration + extra)
        QTimer.singleShot(duration, self._dismiss)

    def _apply_theme(self):
        """Colours from the current theme. Read at show time and again
        on every switch, never at import."""
        toks = T.tokens()
        bg = toks.get(_FILL_TOKENS.get(self._kind, "accent.primary"),
                      toks["accent.primary"])
        self.setStyleSheet(
            f"background: {bg}; color: {toks['accent.on_primary']};"
            f" border-radius: 6px;"
            f" font-size: {T.FONT_SIZE_SM}pt; font-weight: 500;"
        )

    def _fit(self, parent):
        """Size to the text; wrap what does not fit beside the margins."""
        pw = parent.width() if parent is not None else 400
        limit = max(160, min(_MAX_WIDTH, pw - 2 * T.PAD_LG))
        self.setWordWrap(False)
        self.setMaximumWidth(16777215)
        self.adjustSize()
        if self.sizeHint().width() > limit:
            self.setWordWrap(True)
            self.setFixedWidth(limit)
            self.setFixedHeight(self.heightForWidth(limit))
        else:
            self.setFixedHeight(self.sizeHint().height())

    def _announce(self, message):
        """Tell assistive technology: a toast never takes focus, so a
        screen reader would not read it otherwise."""
        self.setAccessibleName(message or "")
        try:
            from PySide6.QtGui import QAccessible, QAccessibleEvent
            QAccessible.updateAccessibility(
                QAccessibleEvent(self, QAccessible.Event.Alert))
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            parent = self._parent_ref() if self._parent_ref else None
            if obj is parent:
                _restack(parent)
        return False

    def _dismiss(self):
        try:
            T.off_theme_change(self._apply_theme)
            parent = self._parent_ref() if self._parent_ref else None
            if parent is not None:
                siblings = _live.get(parent)
                if siblings and self in siblings:
                    siblings.remove(self)
                parent.removeEventFilter(self)
            self.hide()
            self.deleteLater()
            _restack(parent)
        except Exception:
            pass


def _restack(parent):
    """Lay the parent's live toasts out from its top-right corner down."""
    if parent is None:
        return
    try:
        toasts = _live.get(parent) or []
        y = T.PAD_LG
        for toast in list(toasts):
            try:
                toast.move(parent.width() - toast.width() - T.PAD_LG, y)
                y += toast.height() + _GAP
            except RuntimeError:
                toasts.remove(toast)  # deleted with its parent
    except Exception:
        pass
