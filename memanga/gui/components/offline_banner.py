"""
Offline-mode banner — thin strip pinned to the top of the main area
that appears when the network is down and disappears when it recovers.

Visual language matches the design spec:
    - warn-coloured dot prefix (same dot we use in status pills)
    - 12 px label "Offline · Some online features unavailable"
    - subtle right-aligned "Retry" link button
    - background uses warn.soft so it reads as a contextual notice,
      not an error toast
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from .. import theme as T


class OfflineBanner(QWidget):
    """Thin context strip that shows only when network is offline.

    Subscribes to the NetworkMonitor events via the supplied EventBus.
    Call `set_online(bool)` directly for manual control (tests).
    """

    HEIGHT = 30

    def __init__(self, parent, *, events=None, on_retry=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_retry = on_retry

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)

        # Leading dot (painted in paintEvent so it tracks theme)
        self._dot = _StatusDot(self, kind="warn")
        layout.addWidget(self._dot)

        self._label = QLabel("Offline  ·  Some online features are unavailable")
        layout.addWidget(self._label)
        layout.addStretch(1)

        self._retry_btn = QPushButton("Retry now")
        self._retry_btn.setProperty("variant", "ghost")
        self._retry_btn.setProperty("size", "sm")
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_btn.clicked.connect(self._handle_retry)
        layout.addWidget(self._retry_btn)

        self._apply_theme()
        T.on_theme_change(self._apply_theme)

        if events is not None:
            events.subscribe("network_offline", lambda _d: self.set_online(False))
            events.subscribe("network_online", lambda _d: self.set_online(True))

        # Hidden by default — only show on confirmed offline event.
        self.hide()

    # ── API ───────────────────────────────────────────────────────

    def set_online(self, online: bool):
        self.setVisible(not online)

    # ── internals ─────────────────────────────────────────────────

    def _handle_retry(self):
        if callable(self._on_retry):
            self._on_retry()

    def _apply_theme(self):
        toks = T.tokens()
        # Soft warn tint so it reads as a contextual notice, not a
        # screaming error.
        warn_soft = toks.get("accent.warn_soft") or toks.get("status.warn_soft") \
                    or "rgba(255,180,60,0.10)"
        warn = toks.get("accent.warn") or toks.get("status.warn") or "#E0A93B"
        t1 = toks.get("text.t_1", "#FFFFFF")
        border = toks.get("surfaces.border", "rgba(255,255,255,0.06)")
        self.setStyleSheet(
            f"OfflineBanner {{"
            f"  background-color: {warn_soft};"
            f"  border-bottom: 1px solid {border};"
            f"}}"
        )
        self._label.setStyleSheet(
            f"color: {t1}; font-size: 10pt; font-weight: 500;"
        )


class _StatusDot(QWidget):
    """Small coloured dot used as the leading marker on the banner."""

    def __init__(self, parent, *, kind: str = "warn", diameter: int = 8):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._kind = kind
        T.on_theme_change(self.update)

    def paintEvent(self, _ev):
        toks = T.tokens()
        color = (toks.get(f"status.{self._kind}")
                 or toks.get(f"accent.{self._kind}")
                 or "#E0A93B")
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(0, 0, self.width(), self.height())
        finally:
            p.end()
