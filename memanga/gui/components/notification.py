"""
Notification panel popup.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame,
)
from PySide6.QtCore import Qt
from .. import theme as T


class NotificationPanel(QDialog):
    """Floating notification center."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.setWindowTitle("Notifications")
        self.setFixedSize(360, 450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD_LG)

        # Header
        header = QHBoxLayout()
        title = QLabel("Notifications")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        mark_btn = QPushButton("Mark Read")
        mark_btn.setFixedHeight(26)
        mark_btn.clicked.connect(lambda: (app.app_state.mark_notifications_read(), self.close()))
        header.addWidget(mark_btn)
        layout.addLayout(header)

        # Scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        notifications = app.app_state.get_notifications(50)
        if not notifications:
            empty = QLabel("No notifications yet")
            empty.setStyleSheet(f"color: {T.FG_MUTED}; padding: 40px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.addWidget(empty)
        else:
            type_colors = {"download": T.SUCCESS, "check": T.ACCENT, "error": T.ERROR, "kindle": "#8b5cf6"}
            for n in notifications:
                row = QFrame()
                row.setStyleSheet(f"background: {T.BG_CARD}; border-radius: 4px; padding: 6px;")
                rl = QHBoxLayout(row)
                rl.setContentsMargins(T.PAD_SM, T.PAD_XS, T.PAD_SM, T.PAD_XS)

                dot_color = type_colors.get(n.get("type", ""), T.FG_MUTED)
                dot = QLabel("\u2022")
                dot.setStyleSheet(f"color: {dot_color}; font-size: {T.FONT_SIZE_MD}pt;")
                dot.setFixedWidth(16)
                rl.addWidget(dot)

                msg = QLabel(n.get("message", ""))
                msg.setWordWrap(True)
                msg.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
                rl.addWidget(msg, 1)

                ts = n.get("timestamp", "")
                if "T" in ts:
                    ts = ts.split("T")[1][:5]
                time_label = QLabel(ts)
                time_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
                rl.addWidget(time_label)

                content_layout.addWidget(row)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        self.exec()
