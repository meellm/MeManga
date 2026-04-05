"""
Manga list row for list view.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtGui import QPixmap, QMouseEvent
from PySide6.QtCore import Qt
from .. import theme as T


class MangaRow(QFrame):
    """Clickable list row with thumbnail, title, source, status."""

    def __init__(self, parent, manga: dict, state_data: dict = None,
                 cover_image: QPixmap = None, on_click=None, on_right_click=None,
                 new_count: int = 0):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.PAD_MD, T.PAD_SM, T.PAD_MD, T.PAD_SM)
        layout.setSpacing(T.PAD_MD)

        # Thumbnail
        if cover_image:
            thumb = QLabel()
            thumb.setFixedSize(36, 48)
            thumb.setPixmap(cover_image.scaled(36, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(thumb)

        # Info
        info = QVBoxLayout()
        info.setSpacing(2)

        title_row = QHBoxLayout()
        title_label = QLabel(manga.get("title", "Unknown"))
        title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        title_row.addWidget(title_label)

        if new_count > 0:
            badge = QLabel(f" {new_count} NEW ")
            badge.setStyleSheet(f"background: {T.ACCENT}; color: #fff; font-size: {T.FONT_SIZE_XS}pt; font-weight: bold; border-radius: 3px; padding: 0 3px;")
            title_row.addWidget(badge)
        title_row.addStretch()
        info.addLayout(title_row)

        source = manga.get("source", "")
        if not source:
            sources = manga.get("sources", [])
            source = sources[0].get("source", "") if sources else ""
        sub = QLabel(source)
        sub.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        info.addWidget(sub)

        layout.addLayout(info, 1)

        # Right: status + chapters
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        status = manga.get("status", "reading")
        color = T.STATUS_COLORS.get(status, T.FG_MUTED)
        sl = QLabel(status.capitalize())
        sl.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")
        sl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(sl)

        if state_data:
            dl_count = len(state_data.get("downloaded", []))
            cl = QLabel(f"{dl_count} ch.")
            cl.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            cl.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(cl)

        layout.addLayout(right)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._manga)
        elif event.button() == Qt.MouseButton.RightButton and self._on_right_click:
            pos = event.globalPosition().toPoint()
            self._on_right_click(self._manga, pos.x(), pos.y())
