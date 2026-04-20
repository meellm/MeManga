"""
Downloads page - Active/Completed/History with tab navigation.
"""

import subprocess
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget,
)
from PySide6.QtCore import Qt, QTimer
from .base import BasePage
from .. import theme as T
from ..components.progress_item import ProgressItem
from ..components.toast import Toast


class DownloadsPage(BasePage):
    """Downloads view with Active/Completed/History tabs."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._active_items: dict[str, ProgressItem] = {}
        self._completed_widgets: list = []
        self._history_widgets: list = []
        self._current_tab = "active"
        self._build()

        self.app.events.subscribe("download_started", self._on_started)
        self.app.events.subscribe("download_progress", self._on_progress)
        self.app.events.subscribe("download_complete", self._on_complete)
        self.app.events.subscribe("download_error", self._on_error)
        self.app.events.subscribe("download_queued", self._on_queued)
        self.app.events.subscribe("download_cancelled", self._on_cancelled)
        self.app.events.subscribe("check_complete", self._on_check_complete)
        self.app.events.subscribe("check_error", self._on_check_error)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_SM)
        layout.setSpacing(T.PAD_SM)

        # Header
        header = QHBoxLayout()
        title = QLabel("Downloads")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        cancel_all_btn = QPushButton("Cancel All")
        cancel_all_btn.setProperty("class", "danger")
        cancel_all_btn.setFixedHeight(30)
        cancel_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_all_btn.clicked.connect(self._cancel_all)
        header.addWidget(cancel_all_btn)
        layout.addLayout(header)

        # Tab bar
        tab_bar = QHBoxLayout()
        self._tab_buttons: dict[str, QPushButton] = {}
        for tab_name in ["Active", "Completed", "History"]:
            btn = QPushButton(tab_name)
            btn.setProperty("class", "tab")
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=tab_name.lower(): self._switch_tab(t))
            tab_bar.addWidget(btn)
            self._tab_buttons[tab_name.lower()] = btn
        tab_bar.addStretch()
        layout.addLayout(tab_bar)

        # ── Active tab ──
        self._active_scroll = QScrollArea()
        self._active_scroll.setWidgetResizable(True)
        self._active_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._active_content = QWidget()
        self._active_layout = QVBoxLayout(self._active_content)
        self._active_layout.setSpacing(2)
        self._active_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._active_scroll.setWidget(self._active_content)

        self._empty_label = QLabel("No active downloads")
        self._empty_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED}; padding: {T.PAD_XL}px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active_layout.addWidget(self._empty_label)

        # ── Completed tab ──
        self._completed_scroll = QScrollArea()
        self._completed_scroll.setWidgetResizable(True)
        self._completed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._completed_content = QWidget()
        self._completed_layout = QVBoxLayout(self._completed_content)
        self._completed_layout.setSpacing(2)
        self._completed_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._completed_scroll.setWidget(self._completed_content)

        # ── History tab ──
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history_content = QWidget()
        self._history_layout = QVBoxLayout(self._history_content)
        self._history_layout.setSpacing(1)
        self._history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._history_scroll.setWidget(self._history_content)

        # Add all tab frames to layout (visibility managed by _switch_tab)
        layout.addWidget(self._active_scroll, 1)
        layout.addWidget(self._completed_scroll, 1)
        layout.addWidget(self._history_scroll, 1)

        self._switch_tab("active")

    def _switch_tab(self, tab_name):
        self._current_tab = tab_name

        self._active_scroll.setVisible(tab_name == "active")
        self._completed_scroll.setVisible(tab_name == "completed")
        self._history_scroll.setVisible(tab_name == "history")

        for name, btn in self._tab_buttons.items():
            is_active = (name == tab_name)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if tab_name == "history":
            self._render_history()

    def _render_history(self):
        for w in self._history_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._history_widgets.clear()

        history = self.app.app_state.get_download_history(200)

        if not history:
            lbl = QLabel("No download history yet")
            lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED}; padding: {T.PAD_XL}px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_layout.addWidget(lbl)
            self._history_widgets.append(lbl)
            return

        for h in history:
            row = QFrame()
            row.setProperty("class", "card")
            row.setFixedHeight(32)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)
            row_layout.setSpacing(T.PAD_SM)

            ts = h.get("timestamp", "")
            if "T" in ts:
                ts = ts.split("T")[0]

            h_title = h.get("title", "")
            if len(h_title) > 30:
                h_title = h_title[:28] + ".."

            ts_label = QLabel(ts)
            ts_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            ts_label.setFixedWidth(90)
            row_layout.addWidget(ts_label)

            title_label = QLabel(h_title)
            title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
            row_layout.addWidget(title_label, 1)

            ch_label = QLabel(f"Ch.{h.get('chapter', '?')}")
            ch_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
            ch_label.setFixedWidth(60)
            row_layout.addWidget(ch_label)

            fmt_label = QLabel(h.get("format", ""))
            fmt_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
            fmt_label.setFixedWidth(40)
            row_layout.addWidget(fmt_label)

            size_label = QLabel(f"{h.get('size_mb', 0):.1f}MB")
            size_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
            size_label.setFixedWidth(55)
            row_layout.addWidget(size_label)

            self._history_layout.addWidget(row)
            self._history_widgets.append(row)

    def on_show(self, **kwargs):
        if self._current_tab == "history":
            self._render_history()

    # ── Download event handlers ──

    def _update_empty_state(self):
        try:
            self._empty_label.setVisible(len(self._active_items) == 0)
        except Exception:
            pass

    def _on_started(self, data):
        task_id = data["task_id"]
        if task_id in self._active_items:
            return
        item = ProgressItem(
            self._active_content, task_id=task_id,
            title=data["title"], chapter=str(data["chapter"]),
            on_cancel=self._cancel_download,
        )
        self._active_layout.addWidget(item)
        self._active_items[task_id] = item
        self._update_empty_state()

    def _on_queued(self, data):
        task_id = data["task_id"]
        if task_id in self._active_items:
            return
        item = ProgressItem(
            self._active_content, task_id=task_id,
            title=data["title"], chapter=str(data["chapter"]),
            on_cancel=self._cancel_download,
        )
        self._active_layout.addWidget(item)
        self._active_items[task_id] = item
        self._update_empty_state()

    def _on_progress(self, data):
        item = self._active_items.get(data["task_id"])
        if item:
            item.update_progress(data["current"], data["total"])

    def _on_complete(self, data):
        task_id = data["task_id"]
        item = self._active_items.get(task_id)
        if item:
            item.set_complete(data.get("path"))
            QTimer.singleShot(2000, lambda tid=task_id, d=data: self._move_to_completed(tid, d))

    def _on_error(self, data):
        item = self._active_items.get(data["task_id"])
        if item:
            item.set_error(data.get("error", "Unknown error"))

    def _on_cancelled(self, data):
        item = self._active_items.pop(data["task_id"], None)
        if item:
            try:
                item.deleteLater()
            except Exception:
                pass
        self._update_empty_state()

    def _cancel_download(self, task_id):
        self.app.worker.cancel_download(task_id)

    def _cancel_all(self):
        # Order matters: set cancel flags on every queued item AND clear
        # the queue inside the same lock acquisition. Otherwise
        # _start_next_download can pop a queued item between us cancelling
        # actives and clearing — and that fresh task wouldn't have its
        # cancel flag set, defeating Round 2's whole cancel fix.
        with self.app.worker._lock:
            for item in self.app.worker._download_queue:
                item["cancel"].set()
            self.app.worker._download_queue.clear()
        for task_id in list(self._active_items.keys()):
            self.app.worker.cancel_download(task_id)
        Toast(self, "Cancelled all downloads", kind="warning")

    def _move_to_completed(self, task_id, data):
        item = self._active_items.pop(task_id, None)
        if item:
            try:
                item.deleteLater()
            except Exception:
                pass

        row = QFrame()
        row.setProperty("class", "card")
        row.setFixedHeight(36)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(T.PAD_MD, 0, T.PAD_MD, 0)

        label_text = f"{data.get('title', '')} - Ch. {data.get('chapter', '')}"
        label = QLabel(label_text)
        label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        row_layout.addWidget(label, 1)

        path = data.get("path")
        if path:
            open_btn = QPushButton("Open")
            open_btn.setFixedSize(60, 24)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.clicked.connect(lambda checked=False, p=path: self._open_folder(p))
            row_layout.addWidget(open_btn)

        self._completed_layout.addWidget(row)
        self._completed_widgets.append(row)
        self._update_empty_state()

    def _open_folder(self, path):
        try:
            folder = str(Path(path).parent)
            if sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    # ── Check event handlers ──

    def _on_check_error(self, data):
        title = data.get("title", "")
        error = data.get("error", "Unknown error")
        Toast(self, f"Error: {title}: {error[:50]}", kind="error")

    def _on_check_complete(self, data):
        results = data.get("results", [])

        # Filter to auto-mode manga that actually have new chapters to queue.
        # Manual-mode manga surface their badge + per-chapter Download buttons
        # on the Detail page; we never auto-queue for them.
        auto_results = [
            r for r in results
            if r["manga"].get("mode", "auto") == "auto" and r.get("chapters")
        ]

        if not auto_results:
            # Nothing to queue. Show an informational toast distinguishing
            # "nothing found" from "found, but waiting for user action".
            manual_with_new = sum(
                len(r["chapters"]) for r in results
                if r["manga"].get("mode", "auto") == "manual" and r.get("chapters")
            )
            if manual_with_new:
                Toast(
                    self,
                    f"{manual_with_new} new chapter(s) available — open the manga to download",
                    kind="info",
                )
            else:
                Toast(self, "No new chapters found", kind="info")
            return

        total = sum(len(r["chapters"]) for r in auto_results)
        Toast(self, f"Found {total} new chapter(s), downloading...", kind="success")

        global_kindle = self.app.config.delivery_mode == "email" and self.app.config.email_enabled
        naming_template = self.app.config.get("delivery.naming_template")

        for r in auto_results:
            manga = r["manga"]
            for ch in r["chapters"]:
                kindle_cfg = None
                if global_kindle and manga.get("send_to_kindle", True):
                    from ...config import get_app_password
                    kindle_cfg = {
                        "kindle_email": self.app.config.get("email.kindle_email"),
                        "sender_email": self.app.config.get("email.sender_email"),
                        "app_password": get_app_password(self.app.config),
                        "smtp_server": self.app.config.get("email.smtp_server", "smtp.gmail.com"),
                        "smtp_port": self.app.config.get("email.smtp_port", 587),
                    }

                self.app.worker.download_chapter(
                    manga=manga, chapter=ch,
                    output_dir=self.app.config.download_dir,
                    output_format=self.app.config.output_format,
                    state=self.app.app_state, kindle_cfg=kindle_cfg,
                    naming_template=naming_template,
                )
