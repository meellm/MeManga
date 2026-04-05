"""
Add Manga dialog - Modal window to add a new manga.
"""

import threading
from urllib.parse import urlparse
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QWidget,
)
from PySide6.QtCore import Qt
from .. import theme as T
from ..components.toast import Toast


class AddMangaDialog(QDialog):
    """Modal dialog to add a new manga."""

    def __init__(self, parent, app, prefill=None):
        super().__init__(parent)
        self.app = app

        self.setWindowTitle("Add Manga")
        self.setFixedSize(480, 420)
        self.setModal(True)

        self._build(prefill)

    def _build(self, prefill):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_XL)
        layout.setSpacing(T.PAD_SM)

        # Title field
        title_lbl = QLabel("Manga Title")
        title_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        layout.addWidget(title_lbl)

        self._title_entry = QLineEdit()
        self._title_entry.setPlaceholderText("e.g. One Piece")
        self._title_entry.setFixedHeight(34)
        layout.addWidget(self._title_entry)

        layout.addSpacing(T.PAD_SM)

        # URL field
        url_lbl = QLabel("Source URL")
        url_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        layout.addWidget(url_lbl)

        self._url_entry = QLineEdit()
        self._url_entry.setPlaceholderText("https://mangadex.org/title/...")
        self._url_entry.setFixedHeight(34)
        self._url_entry.textChanged.connect(self._on_url_change)
        layout.addWidget(self._url_entry)

        self._source_label = QLabel("")
        self._source_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
        layout.addWidget(self._source_label)

        layout.addSpacing(T.PAD_SM)

        # Backup source toggle
        self._backup_check = QCheckBox("Add backup source")
        self._backup_check.stateChanged.connect(self._toggle_backup)
        layout.addWidget(self._backup_check)

        # Backup frame (hidden by default)
        self._backup_frame = QWidget()
        backup_layout = QVBoxLayout(self._backup_frame)
        backup_layout.setContentsMargins(0, 0, 0, 0)
        backup_layout.setSpacing(T.PAD_SM)

        backup_url_lbl = QLabel("Backup URL")
        backup_url_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; font-weight: bold;")
        backup_layout.addWidget(backup_url_lbl)

        self._backup_url_entry = QLineEdit()
        self._backup_url_entry.setPlaceholderText("https://...")
        self._backup_url_entry.setFixedHeight(34)
        backup_layout.addWidget(self._backup_url_entry)

        delay_row = QHBoxLayout()
        delay_lbl = QLabel("Fallback delay (days):")
        delay_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        delay_row.addWidget(delay_lbl)

        self._delay_entry = QLineEdit("2")
        self._delay_entry.setFixedWidth(50)
        self._delay_entry.setFixedHeight(28)
        delay_row.addWidget(self._delay_entry)
        delay_row.addStretch()
        backup_layout.addLayout(delay_row)

        self._backup_frame.setVisible(False)
        layout.addWidget(self._backup_frame)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setFixedWidth(90)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        add_btn = QPushButton("Add Manga")
        add_btn.setProperty("class", "accent")
        add_btn.setFixedHeight(36)
        add_btn.setFixedWidth(120)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_manga)
        btn_row.addWidget(add_btn)

        layout.addLayout(btn_row)

        # Prefill
        if prefill:
            self._title_entry.setText(prefill.get("title", ""))
            self._url_entry.setText(prefill.get("url", ""))
            self._on_url_change()

        self._title_entry.setFocus()

    def _toggle_backup(self, state):
        self._backup_frame.setVisible(self._backup_check.isChecked())

    def _on_url_change(self, text=None):
        url = self._url_entry.text().strip()
        if url:
            try:
                domain = urlparse(url).netloc.replace("www.", "")
                from ...downloader import get_supported_sources
                sources = get_supported_sources()
                if domain in sources:
                    self._source_label.setText(f"Source: {domain}")
                    self._source_label.setStyleSheet(
                        f"font-size: {T.FONT_SIZE_SM}pt; color: {T.SUCCESS};"
                    )
                else:
                    self._source_label.setText(f"Unknown: {domain}")
                    self._source_label.setStyleSheet(
                        f"font-size: {T.FONT_SIZE_SM}pt; color: {T.WARNING};"
                    )
            except Exception:
                self._source_label.setText("")
        else:
            self._source_label.setText("")

    def _add_manga(self):
        title = self._title_entry.text().strip()
        url = self._url_entry.text().strip()

        if not title or not url:
            return

        existing = self.app.config.get("manga", [])
        for m in existing:
            if m.get("title", "").lower() == title.lower():
                return

        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            return

        if self._backup_check.isChecked() and self._backup_url_entry.text().strip():
            backup_url = self._backup_url_entry.text().strip()
            backup_domain = urlparse(backup_url).netloc.replace("www.", "")
            try:
                delay = int(self._delay_entry.text().strip())
            except ValueError:
                delay = 2
            entry = {
                "title": title,
                "status": "reading",
                "fallback_delay_days": delay,
                "sources": [
                    {"url": url, "source": domain},
                    {"url": backup_url, "source": backup_domain},
                ],
            }
        else:
            entry = {
                "title": title,
                "status": "reading",
                "source": domain,
                "url": url,
            }

        existing.append(entry)
        self.app.config.set("manga", existing)
        self.app.config.save()

        # Fetch cover in background
        def _fetch_cover():
            try:
                from ...scrapers import get_scraper
                scraper = get_scraper(domain)
                if hasattr(scraper, "get_cover_url"):
                    cover = scraper.get_cover_url(url)
                    if cover:
                        manga_list = self.app.config.get("manga", [])
                        for m in manga_list:
                            if m.get("title") == title:
                                m["cover_url"] = cover
                                break
                        self.app.config.save()
            except Exception:
                pass

        threading.Thread(target=_fetch_cover, daemon=True).start()

        # Auto-check for chapters
        self.app.worker.check_updates([entry], self.app.app_state, self.app.config)

        self.accept()
