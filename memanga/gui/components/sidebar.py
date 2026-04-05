"""
Sidebar navigation component.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt
from .. import theme as T


NAV_ITEMS = [
    ("library",   "Library"),
    ("downloads", "Downloads"),
    ("search",    "Search"),
    ("settings",  "Settings"),
]


class Sidebar(QWidget):
    """Fixed left sidebar with navigation buttons."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.setObjectName("sidebar")
        self.setFixedWidth(T.SIDEBAR_WIDTH)

        self._buttons: dict[str, QPushButton] = {}
        self._active_page = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_MD, T.PAD_LG, T.PAD_MD, T.PAD_MD)
        layout.setSpacing(2)

        # Logo
        logo = QLabel("MeManga")
        logo.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold; color: {T.ACCENT};")
        layout.addWidget(logo)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {T.BORDER}; max-height: 1px; border: none;")
        layout.addWidget(line)
        layout.addSpacing(T.PAD_SM)

        # Nav buttons
        for page_name, label in NAV_ITEMS:
            btn = QPushButton(f"  {label}")
            btn.setProperty("class", "nav")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda checked=False, p=page_name: self.app.show_page(p))
            layout.addWidget(btn)
            self._buttons[page_name] = btn

        layout.addStretch(1)

        # Notifications
        self._bell_btn = QPushButton("  Notifications")
        self._bell_btn.setProperty("class", "flat")
        self._bell_btn.setFixedHeight(30)
        self._bell_btn.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        self._bell_btn.clicked.connect(self._show_notifications)
        layout.addWidget(self._bell_btn)

        # Theme toggle
        self._theme_btn = QPushButton("  Dark Mode")
        self._theme_btn.setProperty("class", "flat")
        self._theme_btn.setFixedHeight(30)
        self._theme_btn.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)
        self._update_theme_label()

        self.app.events.subscribe("notification_added", lambda d: self._update_badge())

    def _show_notifications(self):
        from .notification import NotificationPanel
        NotificationPanel(self, self.app)
        self.app.app_state.mark_notifications_read()
        self._update_badge()

    def _update_badge(self):
        try:
            count = self.app.app_state.get_unread_count()
            if count > 0:
                self._bell_btn.setText(f"  Notifications ({min(count, 99)})")
            else:
                self._bell_btn.setText("  Notifications")
        except Exception:
            pass

    def _toggle_theme(self):
        current = self.app.config.get("gui.theme", "dark")
        new_mode = "light" if current == "dark" else "dark"
        self.app.config.set("gui.theme", new_mode)
        self.app.config.save()
        self.app.apply_theme(new_mode)
        self._update_theme_label()

    def _update_theme_label(self):
        mode = self.app.config.get("gui.theme", "dark")
        self._theme_btn.setText("  Light Mode" if mode == "dark" else "  Dark Mode")

    def set_active(self, page_name: str):
        for name, btn in self._buttons.items():
            btn.setProperty("active", "true" if name == page_name else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._active_page = page_name
