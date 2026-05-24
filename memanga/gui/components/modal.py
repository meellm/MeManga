"""
Modal dialog chrome — frameless, centered, head/body/foot.

Matches memanga-pyside6-spec.json `components.modal` + `modal_overlay`:
- Frameless QDialog, transparent background
- Darkened backdrop (rgba 0.6) fills the parent window
- Centered modal panel (520px default, 440px small) with rounded corners
- Three sections:
    * head — title + close icon-button
    * body — content
    * foot — bg_0, right-aligned action buttons
- Fade-in 180ms + 8px translate on open
- Close on backdrop click, Esc, or close X button
"""

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QPoint, QRect,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsOpacityEffect,
)

from .. import theme as T
from ..assets.icons import icon


class ModalDialog(QDialog):
    """Base class for all app modals. Subclasses populate the body via
    :meth:`build_body` and may push extra buttons into :attr:`foot_layout`.

    Use :meth:`build_body` to add fields. The default chrome already has:
      - dim backdrop
      - centered panel with head (title + close X) and foot (button row)
    """

    def __init__(self, parent: QWidget, title: str, *, width: int = 520):
        # Pass the topmost window as parent so the modal centers in it.
        top = parent.window() if parent else None
        super().__init__(top)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        # Cover the whole parent so we paint our own backdrop.
        if top:
            self.setGeometry(top.geometry())
            self.resize(top.size())

        self._panel_width = width

        # ── Backdrop layer ──
        # Painted in self.paintEvent; clicking it (anywhere outside the
        # panel) closes the modal.

        # ── Panel container, centered ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)

        self.panel = QFrame()
        self.panel.setObjectName("modal_panel")
        self.panel.setFixedWidth(self._panel_width)
        self.panel.setStyleSheet(
            f"#modal_panel {{"
            f"  background-color: {T.tokens()['surfaces.bg_1']};"
            f"  border: 1px solid {T.tokens()['surfaces.border_strong']};"
            f"  border-radius: 12px;"
            f"}}"
        )
        center_row.addWidget(self.panel)
        center_row.addStretch(1)
        outer.addLayout(center_row)
        outer.addStretch(1)

        panel_l = QVBoxLayout(self.panel)
        panel_l.setContentsMargins(0, 0, 0, 0)
        panel_l.setSpacing(0)

        # ── Head ──
        head = QWidget()
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(22, 18, 14, 18)
        head_l.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
        head_l.addWidget(title_lbl)
        head_l.addStretch(1)

        close_btn = QPushButton()
        close_btn.setProperty("variant", "ghost")
        close_btn.setIcon(icon("x_close", T.tokens()["text.t_2"], 14))
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        head_l.addWidget(close_btn)
        panel_l.addWidget(head)

        head_sep = QFrame()
        head_sep.setFixedHeight(1)
        head_sep.setStyleSheet(f"background-color: {T.tokens()['surfaces.border']};")
        panel_l.addWidget(head_sep)

        # ── Body ──
        self._body_w = QWidget()
        self.body_layout = QVBoxLayout(self._body_w)
        self.body_layout.setContentsMargins(22, 22, 22, 22)
        self.body_layout.setSpacing(16)
        panel_l.addWidget(self._body_w)

        # ── Foot ── (built BEFORE build_body() so subclasses can push
        # their primary action button into foot_layout / reference cancel_btn)
        foot = QWidget()
        foot.setStyleSheet(
            f"background-color: {T.tokens()['surfaces.bg_0']};"
            f"border-top: 1px solid {T.tokens()['surfaces.border']};"
            f"border-bottom-left-radius: 12px;"
            f"border-bottom-right-radius: 12px;"
        )
        self.foot_layout = QHBoxLayout(foot)
        self.foot_layout.setContentsMargins(16, 16, 22, 16)
        self.foot_layout.setSpacing(8)
        self.foot_layout.addStretch(1)
        # Default Cancel — subclass can replace text or add buttons after it.
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.foot_layout.addWidget(self.cancel_btn)
        panel_l.addWidget(foot)

        # Hook for subclasses to add fields. Cancel_btn + foot_layout are
        # available now.
        self.build_body()

        # Fade-in + translate animation
        self._eff = QGraphicsOpacityEffect(self.panel)
        self._eff.setOpacity(0.0)
        self.panel.setGraphicsEffect(self._eff)
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def build_body(self):
        """Subclass hook — populate self.body_layout with fields."""
        pass

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def paintEvent(self, _ev):
        # Dim backdrop.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 153))
        p.end()

    def mousePressEvent(self, ev):
        # Click outside the panel = close.
        if not self.panel.geometry().contains(ev.pos()):
            self.reject()
        super().mousePressEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(ev)


# ─────────────────────────────────────────────────────────────────────────
# Helper widgets that match the HTML field-group / field-label style
# ─────────────────────────────────────────────────────────────────────────

def field_label(text: str, opt_text: str = "") -> QLabel:
    """Render the field label + optional `(optional)` greyed suffix."""
    body = text
    if opt_text:
        body += f"  <span style='color:{T.tokens()['text.t_3']};font-weight:400'>{opt_text}</span>"
    lbl = QLabel(body)
    lbl.setStyleSheet(
        f"color: {T.tokens()['text.t_1']}; font-size: 12pt; font-weight: 500;"
    )
    return lbl


def field_hint(text: str) -> QLabel:
    """Sub-text hint under a field."""
    lbl = QLabel(text)
    lbl.setProperty("role", "hint")
    return lbl
