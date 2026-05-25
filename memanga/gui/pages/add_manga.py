"""
Add Manga modal — new chrome wrapping the existing add-manga backend.

Public class name and signature are unchanged: callers still do
    AddMangaDialog(parent, app, prefill=None).exec()

Internally we now inherit from ModalDialog so the modal looks like the
HTML reference (rounded panel, fade-in, backdrop dim, head/body/foot).
"""

import threading
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox,
    QComboBox, QWidget,
)
from PySide6.QtCore import Qt

from .. import theme as T
from ..components.toast import Toast
from ..components.modal import ModalDialog, field_label, field_hint
from ..assets.icons import icon


class AddMangaDialog(ModalDialog):
    """Modal dialog to add a new manga.

    Inherits the new modal chrome — title bar, close button, backdrop,
    centered panel, fade-in animation, Esc-to-close.
    """

    def __init__(self, parent, app, prefill=None):
        self.app = app
        self._prefill = prefill or {}
        super().__init__(parent, title="Add manga to library", width=520)

    # ── ModalDialog.build_body hook ──

    def build_body(self):
        bl = self.body_layout

        # ── Source URL field ──
        bl.addWidget(field_label("Source URL"))
        self._url_entry = QLineEdit()
        self._url_entry.setPlaceholderText("https://mangadex.org/title/…")
        self._url_entry.textChanged.connect(self._on_url_change)
        bl.addWidget(self._url_entry)

        # Source-detected callout, hidden until we see a known host.
        self._source_callout = QWidget()
        sc_l = QHBoxLayout(self._source_callout)
        sc_l.setContentsMargins(10, 8, 10, 8)
        sc_l.setSpacing(8)
        self._source_callout.setStyleSheet(
            f"background-color: {T.tokens()['accent.soft_10']};"
            f"border: 1px solid {T.tokens()['accent.ring']};"
            f"border-radius: 6px;"
        )
        check_lbl = QLabel()
        from PySide6.QtCore import QSize
        check_lbl.setPixmap(
            icon("check", T.tokens()["accent.primary"], 16).pixmap(QSize(16, 16))
        )
        sc_l.addWidget(check_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self._source_callout_text = QLabel("")
        self._source_callout_text.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 12pt;"
        )
        sc_l.addWidget(self._source_callout_text, 1)
        self._source_callout.hide()
        bl.addWidget(self._source_callout)

        # ── Title override field ──
        bl.addWidget(field_label("Title", "override (optional)"))
        self._title_entry = QLineEdit()
        self._title_entry.setPlaceholderText("Auto-detected from URL")
        bl.addWidget(self._title_entry)

        # ── 2-col grid: I'm currently on chapter + reading status ──
        grid_w = QWidget()
        grid_l = QHBoxLayout(grid_w)
        grid_l.setContentsMargins(0, 0, 0, 0)
        grid_l.setSpacing(12)

        col_a = QVBoxLayout()
        col_a.setSpacing(4)
        col_a.addWidget(field_label("I'm currently on chapter", "optional"))
        self._current_entry = QLineEdit()
        self._current_entry.setPlaceholderText("leave blank to start fresh")
        self._current_entry.setProperty("role", "mono")
        self._current_entry.setStyleSheet("font-family: 'Geist Mono', monospace;")
        col_a.addWidget(self._current_entry)
        grid_l.addLayout(col_a, 1)

        col_b = QVBoxLayout()
        col_b.setSpacing(4)
        col_b.addWidget(field_label("Reading status"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["Reading", "Plan to read", "Paused"])
        col_b.addWidget(self._status_combo)
        grid_l.addLayout(col_b, 1)

        bl.addWidget(grid_w)

        # ── Add backup source checkbox + hint ──
        self._backup_check = QCheckBox("Add backup source")
        self._backup_check.setChecked(True)
        self._backup_check.stateChanged.connect(self._toggle_backup)
        bl.addWidget(self._backup_check)
        bl.addWidget(field_hint("Fallback if the primary source is unreachable."))

        # ── Backup URL + delay (collapsed by default — shown when checked) ──
        self._backup_frame = QWidget()
        bf_l = QVBoxLayout(self._backup_frame)
        bf_l.setContentsMargins(0, 6, 0, 0)
        bf_l.setSpacing(6)
        bf_l.addWidget(field_label("Backup URL"))
        self._backup_url_entry = QLineEdit()
        self._backup_url_entry.setPlaceholderText("https://…")
        bf_l.addWidget(self._backup_url_entry)
        delay_row = QHBoxLayout()
        delay_row.addWidget(field_label("Fallback delay (days)"))
        delay_row.addStretch(1)
        self._delay_entry = QLineEdit("2")
        self._delay_entry.setFixedWidth(70)
        self._delay_entry.setProperty("role", "mono")
        delay_row.addWidget(self._delay_entry)
        bf_l.addLayout(delay_row)
        self._backup_frame.setVisible(True)
        bl.addWidget(self._backup_frame)

        # ── Foot: replace default Cancel with Cancel + primary "Add to library"
        # Direct stylesheet on the primary button + the QSS variant so it
        # looks right even on dialogs where the parent's QSS hasn't
        # propagated (frameless top-level dialogs).
        from PySide6.QtCore import QSize
        self.cancel_btn.setText("Cancel")
        add_btn = QPushButton("Add to library")
        add_btn.setProperty("variant", "primary")
        add_btn.setMinimumHeight(34)
        add_btn.setMinimumWidth(170)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setIcon(icon("plus", T.tokens()["accent.on_primary"], 14))
        add_btn.setIconSize(QSize(14, 14))
        add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {T.tokens()['accent.primary']};"
            f"  color: {T.tokens()['accent.on_primary']};"
            f"  border: 1px solid {T.tokens()['accent.primary']};"
            f"  border-radius: 6px;"
            f"  padding: 6px 14px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {T.tokens()['accent.primary_2']};"
            f"  border-color: {T.tokens()['accent.primary_2']};"
            f"}}"
        )
        add_btn.clicked.connect(self._add_manga)
        self.foot_layout.addWidget(add_btn)

        # Prefill if provided.
        if self._prefill:
            self._title_entry.setText(self._prefill.get("title", ""))
            self._url_entry.setText(self._prefill.get("url", ""))
            self._on_url_change()

        self._url_entry.setFocus()

    # ── Event handlers ──

    def _toggle_backup(self, _state):
        self._backup_frame.setVisible(self._backup_check.isChecked())

    def _on_url_change(self, text=None):
        url = self._url_entry.text().strip()
        if not url:
            self._source_callout.hide()
            return
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            from ...downloader import get_supported_sources
            sources = get_supported_sources()
            if domain in sources:
                self._source_callout_text.setText(
                    f"Detected <b>{domain}</b>"
                )
                self._source_callout.show()
            else:
                self._source_callout.hide()
        except Exception:
            self._source_callout.hide()

    def _add_manga(self):
        title = self._title_entry.text().strip()
        url = self._url_entry.text().strip()

        # Title is optional; if blank, derive a placeholder from the URL.
        if not url:
            return
        if not title:
            try:
                last = urlparse(url).path.rstrip("/").split("/")[-1]
                title = last.replace("-", " ").title() or "Untitled"
            except Exception:
                title = "Untitled"

        # Dedupe by case-insensitive title.
        existing = self.app.config.get("manga", [])
        for m in existing:
            if m.get("title", "").lower() == title.lower():
                return

        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            return

        status_map = {"Reading": "reading", "Plan to read": "plan", "Paused": "on-hold"}
        status_val = status_map.get(self._status_combo.currentText(), "reading")

        if self._backup_check.isChecked() and self._backup_url_entry.text().strip():
            backup_url = self._backup_url_entry.text().strip()
            backup_domain = urlparse(backup_url).netloc.replace("www.", "")
            try:
                delay = int(self._delay_entry.text().strip())
            except ValueError:
                delay = 2
            entry = {
                "title": title,
                "status": status_val,
                "mode": "manual",
                "fallback_delay_days": delay,
                "sources": [
                    {"url": url, "source": domain},
                    {"url": backup_url, "source": backup_domain},
                ],
            }
        else:
            entry = {
                "title": title,
                "status": status_val,
                "mode": "manual",
                "source": domain,
                "url": url,
            }

        current_raw = self._current_entry.text().strip()
        if current_raw:
            try:
                float(current_raw)
                entry["external_threshold"] = current_raw
            except ValueError:
                Toast(self, "Current chapter must be a number — leaving blank",
                      kind="warning")

        existing.append(entry)
        self.app.config.set("manga", existing)
        self.app.config.save()

        # Cover fetch in background (scraper first, MangaDex fallback).
        def _fetch_cover():
            cover = None
            try:
                from ...scrapers import get_scraper
                scraper = get_scraper(domain)
                if hasattr(scraper, "get_cover_url"):
                    cover = scraper.get_cover_url(url)
            except Exception:
                cover = None
            if not cover:
                try:
                    from ..cover_fallback import fetch_mangadex_cover
                    cover = fetch_mangadex_cover(title)
                except Exception:
                    cover = None
            if cover:
                manga_list = self.app.config.get("manga", [])
                for m in manga_list:
                    if m.get("title") == title:
                        m["cover_url"] = cover
                        break
                self.app.config.save()

        threading.Thread(target=_fetch_cover, daemon=True).start()

        # Auto-check for chapters
        self.app.worker.check_updates([entry], self.app.app_state, self.app.config)

        self.app.events.publish("library_updated", {"title": title, "action": "add"})
        self.accept()
