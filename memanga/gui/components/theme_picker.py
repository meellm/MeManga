"""
Theme picker — two clickable cards (Dark / Light) with mini preview swatch.

Per memanga-pyside6-spec.json `components.theme_picker_card`. Click to
switch theme instantly (no restart). Selected card gets the accent border.

Mini-preview is rendered via QPainter so it shows the actual palette of
each theme — not the *current* theme.
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
)
from .. import theme as T
from ..theme.tokens import THEMES


class _MiniPreview(QWidget):
    """Tiny pre-rendered preview of what the app looks like in the
    given theme. Mirrors the spec's `theme_picker_card.preview_swatch`.
    """

    def __init__(self, theme_name: str, parent=None):
        super().__init__(parent)
        self._theme_name = theme_name
        self.setFixedHeight(110)
        self.setMinimumWidth(220)

    def paintEvent(self, _ev):
        from ..theme.tokens import flat
        t = flat(THEMES[self._theme_name])

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded card background
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["surfaces.bg_0"]))
        p.drawRoundedRect(rect, radius, radius)

        # Mini-sidebar
        side_w = 56
        side_rect = rect.adjusted(0, 0, -(rect.width() - side_w), 0)
        p.setBrush(QColor(t["surfaces.bg_1"]))
        # Custom roundedness — only left two corners; draw rect + cover right edge
        p.drawRoundedRect(side_rect, radius, radius)
        p.setBrush(QColor(t["surfaces.bg_1"]))
        p.drawRect(side_rect.right() - radius, side_rect.top(),
                   radius + 1, side_rect.height())

        # Logo square
        p.setBrush(QColor(t["accent.primary"]))
        p.drawRoundedRect(8, 8, 18, 18, 4, 4)

        # 3 nav lines
        line_x = 8
        line_y = 36
        line_h = 4
        line_gap = 6
        line_max_w = side_w - 16
        widths = [line_max_w, line_max_w * 0.7, line_max_w]
        for w in widths:
            p.setBrush(QColor(t["surfaces.bg_2"]))
            p.drawRoundedRect(line_x, line_y, int(w), line_h, 2, 2)
            line_y += line_h + line_gap

        # Main area: title bar
        main_x = side_w + 10
        main_y = 10
        main_w = rect.width() - side_w - 14
        p.setBrush(QColor(t["surfaces.bg_2"]))
        p.drawRoundedRect(main_x, main_y, int(main_w * 0.55), 8, 3, 3)

        # 3 mini cover cards
        card_y = main_y + 18
        card_h = rect.height() - card_y - 8
        gap = 6
        # Three cover-like rects with the cover_paint_examples gradients
        from ..theme.tokens import THEMES as _T
        examples = [
            ("#2A3441", "#5A4666"),
            ("#D44A1A", "#F47438"),
            ("#BD3030", "#5A1717"),
        ]
        avail_w = main_w - 4
        card_w = (avail_w - 2 * gap) / 3
        for i, (top, bot) in enumerate(examples):
            x = main_x + i * (card_w + gap)
            g = QLinearGradient(0, card_y, 0, card_y + card_h)
            g.setColorAt(0, QColor(top))
            g.setColorAt(1, QColor(bot))
            p.setBrush(g)
            p.drawRoundedRect(int(x), int(card_y), int(card_w), int(card_h), 4, 4)

        # Border on top of everything
        from PySide6.QtGui import QPen
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(t["surfaces.border"]), 1))
        p.drawRoundedRect(rect, radius, radius)

        p.end()


class _ThemeCard(QFrame):
    """Clickable theme card."""

    clicked = Signal(str)  # emits theme name

    def __init__(self, theme_name: str, parent=None):
        super().__init__(parent)
        self._theme_name = theme_name
        self.setProperty("role", "theme_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        preview = _MiniPreview(theme_name)
        layout.addWidget(preview)

        title_row = QHBoxLayout()
        label = QLabel(THEMES[theme_name]["label"].split("—")[0].strip())
        label.setProperty("role", "card_title")
        title_row.addWidget(label)

        title_row.addStretch(1)

        self._check = QLabel("✓")
        accent = T.tokens()["accent.primary"]
        on_acc = T.tokens()["accent.on_primary"]
        self._check.setFixedSize(22, 22)
        self._check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check.setStyleSheet(
            f"background-color: {accent}; color: {on_acc};"
            f"border-radius: 11px; font-weight: 700;"
        )
        self._check.hide()
        title_row.addWidget(self._check)

        layout.addLayout(title_row)

        desc = QLabel(THEMES[theme_name]["label"].split("—", 1)[1].strip()
                      if "—" in THEMES[theme_name]["label"] else "")
        desc.setProperty("role", "hint")
        layout.addWidget(desc)

    def set_selected(self, selected: bool):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._check.setVisible(selected)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._theme_name)
        super().mousePressEvent(ev)


class ThemePicker(QWidget):
    """Two-card theme switcher (dark + light)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._cards: dict = {}
        for name in ("dark", "light"):
            card = _ThemeCard(name, self)
            card.clicked.connect(self._on_pick)
            layout.addWidget(card, 1)
            self._cards[name] = card

        self._sync()
        T.on_theme_change(self._sync)

    def _on_pick(self, name: str):
        from PySide6.QtWidgets import QApplication
        T.set_theme(name, QApplication.instance())

    def _sync(self):
        cur = T.current_theme()
        for name, card in self._cards.items():
            card.set_selected(name == cur)
