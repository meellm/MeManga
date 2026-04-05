"""
Manga cover card for grid view.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout
from PySide6.QtGui import QPixmap, QMouseEvent
from PySide6.QtCore import Qt
from .. import theme as T


class MangaCard(QFrame):
    """Clickable card with cover image, title, and status."""

    def __init__(self, parent, manga: dict, cover_image: QPixmap, on_click=None,
                 on_right_click=None, new_count: int = 0):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setFixedSize(T.CARD_WIDTH, T.CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, T.PAD_SM)
        layout.setSpacing(T.PAD_XS)

        # Cover
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(T.CARD_WIDTH - 2, T.CARD_COVER_HEIGHT)
        self._cover_label.setPixmap(cover_image.scaled(
            T.CARD_WIDTH - 2, T.CARD_COVER_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setStyleSheet("border-radius: 6px 6px 0 0;")
        layout.addWidget(self._cover_label)

        # Title
        title = manga.get("title", "Unknown")
        if len(title) > 20:
            title = title[:18] + ".."
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold; padding: 0 {T.PAD_SM}px;")
        layout.addWidget(title_label)

        # Status row
        status = manga.get("status", "reading")
        color = T.STATUS_COLORS.get(status, T.FG_MUTED)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)

        status_label = QLabel(status.capitalize())
        status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")
        bottom.addWidget(status_label)

        if new_count > 0:
            badge = QLabel(f" {new_count} NEW ")
            badge.setStyleSheet(
                f"background: {T.ACCENT}; color: #fff; font-size: {T.FONT_SIZE_XS}pt;"
                f" font-weight: bold; border-radius: 3px; padding: 1px 4px;"
            )
            bottom.addWidget(badge)

        bottom.addStretch()
        layout.addLayout(bottom)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._manga)
        elif event.button() == Qt.MouseButton.RightButton and self._on_right_click:
            pos = event.globalPosition().toPoint()
            self._on_right_click(self._manga, pos.x(), pos.y())

    def update_cover(self, cover_image: QPixmap):
        self._cover_label.setPixmap(cover_image.scaled(
            T.CARD_WIDTH - 2, T.CARD_COVER_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
