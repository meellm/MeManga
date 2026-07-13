"""
Downloads page - Active/Completed/History with tab navigation.
"""

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Page header w/ divider (new spec chrome) ──
        header_w = QWidget()
        h_layout = QVBoxLayout(header_w)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Downloads")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)

        from ..assets.icons import icon as _ic
        open_folder_btn = QPushButton("  Open folder")
        open_folder_btn.setProperty("variant", "ghost")
        open_folder_btn.setIcon(_ic("folder", T.tokens()["text.t_2"], 14))
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._open_download_folder)
        top_row.addWidget(open_folder_btn)

        # Pause all / Resume all (toggle).
        self._pause_all_btn = QPushButton("  Pause all")
        self._pause_all_btn.setProperty("variant", "ghost")
        self._pause_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_all_btn.clicked.connect(self._toggle_pause_all)
        top_row.addWidget(self._pause_all_btn)

        self._cancel_all_btn = QPushButton("  Cancel all")
        self._cancel_all_btn.setProperty("variant", "danger")
        self._cancel_all_btn.setIcon(_ic("x_close", T.tokens()["status.danger"], 14))
        self._cancel_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_all_btn.clicked.connect(self._cancel_all)
        # Issue #47: nothing to cancel until a download starts or queues.
        self._cancel_all_btn.setEnabled(False)
        top_row.addWidget(self._cancel_all_btn)
        h_layout.addLayout(top_row)

        # Meta line — live counts are populated by the download / queue
        # event handlers below. Initial render uses placeholder zeros.
        meta = QLabel("● 0 active  ·  0 queued  ·  Auto-refreshed each download event")
        meta.setProperty("role", "meta")
        h_layout.addWidget(meta)

        layout.addWidget(header_w)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # Body wrapper to host the original tabs + scrolls.
        body_w = QWidget()
        body_outer = QVBoxLayout(body_w)
        body_outer.setContentsMargins(32, 20, 32, 20)
        body_outer.setSpacing(T.PAD_SM)
        layout.addWidget(body_w, 1)
        # Re-point local `layout` at the body for the rest of the original
        # build code below, which still uses `layout.addLayout/addWidget`.
        layout = body_outer

        # ── Stats strip: 4 stat cards (matches HTML spec.screens.downloads.stats_strip)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self._stat_cards = {}
        for key, label in [("in_progress","IN PROGRESS"),("today","TODAY"),
                            ("week","THIS WEEK"),("disk","LIBRARY ON DISK")]:
            card = self._make_stat_card(label, "0", "chapters")
            stats_row.addWidget(card, 1)
            self._stat_cards[key] = card
        layout.addLayout(stats_row)
        layout.addSpacing(8)
        # Refresh stats on download events.
        self.app.events.subscribe("download_complete", lambda d: self._refresh_stats())
        self.app.events.subscribe("download_started", lambda d: self._refresh_stats())
        # Initial paint.
        self._stats_pending_first_paint = True

        # Tab bar with live count pills (HTML spec.components.tabs.count_pill).
        tab_bar = QHBoxLayout()
        self._tab_buttons: dict[str, QPushButton] = {}
        self._tab_labels: dict[str, str] = {}
        for tab_name in ["Active", "Completed", "History"]:
            btn = QPushButton(tab_name)
            btn.setProperty("class", "tab")
            btn.setMinimumHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=tab_name.lower(): self._switch_tab(t))
            tab_bar.addWidget(btn)
            key = tab_name.lower()
            self._tab_buttons[key] = btn
            self._tab_labels[key] = tab_name
        tab_bar.addStretch()
        layout.addLayout(tab_bar)
        # Refresh counts whenever downloads change.
        self.app.events.subscribe("download_complete", lambda d: self._refresh_tab_counts())
        self.app.events.subscribe("download_started", lambda d: self._refresh_tab_counts())
        self.app.events.subscribe("download_cancelled", lambda d: self._refresh_tab_counts())
        self.app.events.subscribe("download_queued", lambda d: self._refresh_tab_counts())

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
            row.setMinimumHeight(38)
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
        self._refresh_stats()
        self._refresh_tab_counts()
        self._update_empty_state()

    def _refresh_tab_counts(self):
        """Re-render each tab button label with a trailing count like 'Active 3'."""
        try:
            active_n = len(self._active_items)
            completed_n = len(self.app.app_state.get("completed_downloads") or [])
            history_n = len(self.app.app_state.get("download_history") or [])
        except Exception:
            active_n = completed_n = history_n = 0
        counts = {"active": active_n, "completed": completed_n, "history": history_n}
        for key, btn in self._tab_buttons.items():
            base = self._tab_labels.get(key, key.title())
            n = counts.get(key, 0)
            btn.setText(f"{base}  {n}" if n else base)

    # ── Stats strip helpers ──

    def _make_stat_card(self, label: str, value: str, unit: str) -> QFrame:
        """Build a single stat card matching memanga-pyside6-spec.json
        components.stat_card."""
        card = QFrame()
        card.setProperty("role", "stat_card")
        l = QVBoxLayout(card)
        l.setContentsMargins(14, 12, 14, 12)
        l.setSpacing(4)

        lbl = QLabel(label)
        lbl.setProperty("role", "section")
        l.addWidget(lbl)

        val_row = QHBoxLayout()
        val_row.setSpacing(6)
        val_row.setContentsMargins(0, 0, 0, 0)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet("font-size: 22pt; font-weight: 600;")
        val_lbl.setObjectName("stat_value")
        val_row.addWidget(val_lbl)
        unit_lbl = QLabel(unit)
        unit_lbl.setProperty("role", "t2")
        unit_lbl.setStyleSheet(f"font-size: 11pt; padding-bottom: 4px;")
        unit_lbl.setObjectName("stat_unit")
        val_row.addWidget(unit_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        val_row.addStretch(1)
        l.addLayout(val_row)
        return card

    def _refresh_stats(self):
        """Pull live values from state into the 4 stat cards."""
        try:
            from datetime import datetime, timedelta
            history = self.app.app_state.get("download_history") or []
            now = datetime.now()
            today = sum(1 for h in history
                        if (datetime.fromisoformat(h["timestamp"]).date() == now.date()))
            today_mb = sum(h.get("size_mb", 0) for h in history
                            if datetime.fromisoformat(h["timestamp"]).date() == now.date())
            week = sum(1 for h in history
                        if (now - datetime.fromisoformat(h["timestamp"])).days < 7)
            week_gb = sum(h.get("size_mb", 0) for h in history
                            if (now - datetime.fromisoformat(h["timestamp"])).days < 7) / 1024
            disk_gb = sum(h.get("size_mb", 0) for h in history) / 1024
            active = len(self._active_items)

            self._set_stat("in_progress", str(active), "chapters")
            self._set_stat("today", str(today), f"{today_mb:.1f} MB")
            self._set_stat("week", str(week), f"{week_gb:.2f} GB")
            self._set_stat("disk", f"{disk_gb:.1f}", "GB")
        except Exception:
            # Stats are non-critical — never crash the page.
            pass

    def _set_stat(self, key: str, value: str, unit: str):
        card = self._stat_cards.get(key)
        if not card:
            return
        v = card.findChild(QLabel, "stat_value")
        u = card.findChild(QLabel, "stat_unit")
        if v: v.setText(value)
        if u: u.setText(unit)

    # ── Download event handlers ──

    def _update_empty_state(self):
        # _active_items mirrors both running and queued downloads, so it is
        # the single source of truth for "is there anything to cancel".
        has_items = len(self._active_items) > 0
        try:
            self._empty_label.setVisible(not has_items)
            self._cancel_all_btn.setEnabled(has_items)
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

    def _toggle_pause_all(self):
        """Flip the global pause flag on the worker pool."""
        from ..components.toast import Toast
        if self.app.worker.is_paused():
            self.app.worker.resume_all()
            self._pause_all_btn.setText("  Pause all")
            Toast(self, "Downloads resumed", kind="info")
        else:
            self.app.worker.pause_all()
            self._pause_all_btn.setText("  Resume all")
            Toast(self, "Downloads paused — in-flight jobs continue", kind="info")

    def _open_download_folder(self):
        """Open the download directory in the OS file manager."""
        from .._subprocess import open_in_file_manager
        if not open_in_file_manager(self.app.config.download_dir):
            Toast(self, "Couldn't open the download folder", kind="error")

    def _cancel_all(self):
        # Order matters: set cancel flags on every queued item AND clear
        # the queue inside the same lock acquisition. Otherwise
        # _start_next_download can pop a queued item between us cancelling
        # actives and clearing — and that fresh task wouldn't have its
        # cancel flag set, defeating Round 2's whole cancel fix.
        #
        # Also issue #14: queued tasks that get cleared from the worker
        # queue never actually run, so `_run_download` never publishes
        # download_cancelled for them, so the UI rows ("Waiting…") would
        # linger forever. Capture the queued task_ids while we still
        # hold the lock and synthesize the cancel event ourselves below.
        with self.app.worker._lock:
            queued_task_ids = [it["task_id"] for it in self.app.worker._download_queue]
            for item in self.app.worker._download_queue:
                item["cancel"].set()
            self.app.worker._download_queue.clear()

        # Real cancel-flag set for actually-running tasks. _run_download
        # will publish download_cancelled when its inner loop sees the flag.
        running_task_ids = [
            tid for tid in self._active_items.keys()
            if tid not in queued_task_ids
        ]

        # Issue #47: with nothing running and nothing queued there is
        # nothing to cancel — no events, no "Cancelled" confirmation.
        # The button is disabled in that state, but guard the handler too
        # so a stale click can never report a cancel that didn't happen.
        if not running_task_ids and not queued_task_ids:
            return

        for task_id in running_task_ids:
            self.app.worker.cancel_download(task_id)

        # Synthesize download_cancelled for items that were ONLY queued —
        # they never enter _run_download, so we have to publish on their
        # behalf to drain the UI list and refresh badges/tab counts.
        for task_id in queued_task_ids:
            self.app.events.publish("download_cancelled", {"task_id": task_id})

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
        # `path` is a chapter file; reveal its containing manga folder.
        from .._subprocess import open_in_file_manager
        if not open_in_file_manager(Path(path).parent):
            Toast(self, "Couldn't open the folder", kind="error")

    # ── Check event handlers ──

    def _on_check_error(self, data):
        title = data.get("title", "")
        error = data.get("error", "Unknown error")
        Toast(self, f"Error: {title}: {error[:50]}", kind="error")

    def _on_check_complete(self, data):
        results = data.get("results", [])
        # Set by an explicit "Download All" / "Download from chapter" action.
        # Such a request must queue the resolved chapters regardless of mode;
        # the background sweep only auto-queues auto-mode manga.
        queue_all = data.get("queue_all", False)

        # Manual-mode manga surface their badge + per-chapter Download buttons
        # on the Detail page and are not auto-queued by the background sweep —
        # but an explicit download request (queue_all) does queue them.
        if queue_all:
            to_queue = [r for r in results if r.get("chapters")]
        else:
            to_queue = [
                r for r in results
                if r["manga"].get("mode", "auto") == "auto" and r.get("chapters")
            ]

        if not to_queue:
            if queue_all:
                # Explicit request resolved nothing to download (e.g. every
                # chapter is already on disk).
                Toast(self, "No chapters to download", kind="info")
                return
            # Background sweep: distinguish "nothing found" from "found, but
            # waiting for the user to download from the Detail page".
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

        total = sum(len(r["chapters"]) for r in to_queue)
        Toast(self, f"Found {total} new chapter(s), downloading...", kind="success")

        global_kindle = self.app.config.delivery_mode == "email" and self.app.config.email_enabled
        naming_template = self.app.config.get("delivery.naming_template")

        skipped = 0
        for r in to_queue:
            manga = r["manga"]
            m_title = manga.get("title", "")
            for ch in r["chapters"]:
                # Issue #15: never re-queue a chapter that's already on
                # disk. Belt-and-suspenders against any caller that
                # didn't filter beforehand (Library "Download All",
                # auto-check, etc.).
                if self.app.app_state.is_chapter_downloaded(m_title, str(ch.number)):
                    skipped += 1
                    continue

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
                    allow_partial=self.app.config.partial_enabled,
                    partial_threshold=self.app.config.partial_threshold,
                )
        if skipped:
            Toast(self, f"Skipped {skipped} chapter(s) already on disk", kind="info")
