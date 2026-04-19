"""
Detail page - Manga info, edit, chapters, download from chapter, and actions.
"""

from pathlib import Path
from urllib.parse import urlparse
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QComboBox, QCheckBox, QLineEdit,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T
from ..components.toast import Toast
from ..components.dialogs import ConfirmDialog, InputDialog


class DetailPage(BasePage):
    """Manga detail view with info, edit, chapters, and actions."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._editing = False
        # Container for the merged chapter list — rebuilt independently of the
        # rest of the page when a single download completes.
        self._chapters_container = None
        # task_ids of in-flight per-chapter Download buttons → button widget,
        # so we can flip them to "Read" when their download completes.
        self._pending_downloads: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        self._scroll_content = QWidget()
        self._layout = QVBoxLayout(self._scroll_content)
        self._layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_XL)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._scroll_content)

        # Refresh the chapter list when a single download completes for the
        # currently displayed manga (manual-mode per-chapter Download flow).
        self.app.events.subscribe("download_complete", self._on_any_download_complete)
        # Also refresh after a check completes — newly discovered chapters
        # surface as Download rows immediately, no navigation needed.
        self.app.events.subscribe("check_complete", self._on_any_check_complete)

    def on_show(self, **kwargs):
        manga = kwargs.get("manga")
        if manga:
            self._manga = manga
        self._editing = False
        if self._manga:
            self._rebuild()

    def _get_source_display(self, manga):
        """Extract primary and backup source domains from manga config."""
        sources = manga.get("sources", [])
        if sources:
            primary = sources[0].get("source", sources[0].get("url", ""))
            backup = sources[1].get("source", "") if len(sources) > 1 else ""
            primary_url = sources[0].get("url", "")
            backup_url = sources[1].get("url", "") if len(sources) > 1 else ""
        else:
            primary = manga.get("source", "")
            primary_url = manga.get("url", "")
            backup = ""
            backup_url = ""
        return primary, primary_url, backup, backup_url

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())

    def _clear_child_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())

    def _rebuild(self):
        self._clear_layout()

        manga = self._manga
        title = manga.get("title", "Unknown")
        state_data = self.app.app_state.get_manga_state(title)
        primary, primary_url, backup, backup_url = self._get_source_display(manga)

        # ── Back button ──
        back_btn = QPushButton("<  Back")
        back_btn.setProperty("class", "flat")
        back_btn.setFixedHeight(28)
        back_btn.setFixedWidth(80)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.app.show_page("library"))
        self._layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self._layout.addSpacing(T.PAD_MD)

        # ── Main row: cover left + info right ──
        main_row = QHBoxLayout()
        main_row.setSpacing(T.PAD_XL)

        # Cover
        cover_url = manga.get("cover_url")
        cover_pixmap = self.app.cover_cache.get_cover(cover_url, size=(200, 280))
        cover_label = QLabel()
        cover_label.setFixedSize(200, 280)
        cover_label.setPixmap(cover_pixmap.scaled(
            200, 280,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_label.setStyleSheet(f"border-radius: {T.CARD_RADIUS}px; border: 1px solid {T.BORDER};")
        main_row.addWidget(cover_label, alignment=Qt.AlignmentFlag.AlignTop)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(T.PAD_XS)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        title_label.setWordWrap(True)
        info_layout.addWidget(title_label)

        # Source info
        primary_label = QLabel(f"Primary: {primary}")
        primary_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
        info_layout.addWidget(primary_label)

        if primary_url:
            url_label = QLabel(f"  {primary_url}")
            url_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            url_label.setWordWrap(True)
            info_layout.addWidget(url_label)

        if backup:
            backup_label = QLabel(f"Backup: {backup}")
            backup_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
            info_layout.addWidget(backup_label)
            if backup_url:
                bu_label = QLabel(f"  {backup_url}")
                bu_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
                bu_label.setWordWrap(True)
                info_layout.addWidget(bu_label)

            delay = manga.get("fallback_delay_days", 2)
            delay_label = QLabel(f"Fallback delay: {delay} days")
            delay_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            info_layout.addWidget(delay_label)

        info_layout.addSpacing(T.PAD_SM)

        # Status dropdown
        status_row = QHBoxLayout()
        status_lbl = QLabel("Status:")
        status_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        status_row.addWidget(status_lbl)

        self._status_combo = QComboBox()
        self._status_combo.addItems(["reading", "on-hold", "dropped", "completed"])
        self._status_combo.setCurrentText(manga.get("status", "reading"))
        self._status_combo.setFixedHeight(28)
        self._status_combo.setFixedWidth(130)
        self._status_combo.currentTextChanged.connect(self._on_status_change)
        status_row.addWidget(self._status_combo)
        status_row.addStretch()
        info_layout.addLayout(status_row)

        # Kindle toggle
        global_email_on = (self.app.config.delivery_mode == "email" and self.app.config.email_enabled)
        manga_kindle = manga.get("send_to_kindle", True)

        kindle_row = QHBoxLayout()
        self._kindle_check = QCheckBox("Send to Kindle after download")
        self._kindle_check.setChecked(manga_kindle and global_email_on)
        self._kindle_check.stateChanged.connect(self._on_kindle_toggle)
        kindle_row.addWidget(self._kindle_check)

        if not global_email_on:
            self._kindle_check.setEnabled(False)
            hint = QLabel("(enable email in Settings first)")
            hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
            kindle_row.addWidget(hint)

        kindle_row.addStretch()
        info_layout.addLayout(kindle_row)

        # ── Download mode toggle ──
        # Existing manga without a `mode` field default to "auto" so legacy
        # behavior is preserved. New manga (added via the Add Manga dialog)
        # default to "manual" — users opt into auto-download per series.
        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        mode_row.addWidget(mode_lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Auto", "Manual"])
        current_mode = manga.get("mode", "auto")
        self._mode_combo.setCurrentText("Manual" if current_mode == "manual" else "Auto")
        self._mode_combo.setFixedHeight(28)
        self._mode_combo.setFixedWidth(130)
        self._mode_combo.currentTextChanged.connect(self._on_mode_change)
        mode_row.addWidget(self._mode_combo)

        mode_hint = QLabel(
            "(Manual: download chapters individually below)"
            if current_mode == "manual"
            else "(Auto: new chapters download after each check)"
        )
        mode_hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        mode_row.addWidget(mode_hint)
        self._mode_hint = mode_hint
        mode_row.addStretch()
        info_layout.addLayout(mode_row)

        info_layout.addSpacing(T.PAD_SM)

        # Stats
        downloaded = state_data.get("downloaded", [])
        last_ch = state_data.get("last_chapter") or "-"
        last_updated = state_data.get("last_updated") or "Never"
        if last_updated != "Never" and "T" in last_updated:
            last_updated = last_updated.split("T")[0]

        stats_text = f"Downloaded: {len(downloaded)} chapters  |  Last: Ch. {last_ch}  |  Updated: {last_updated}"
        stats_label = QLabel(stats_text)
        stats_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_SECONDARY};")
        info_layout.addWidget(stats_label)

        info_layout.addSpacing(T.PAD_MD)

        # Action buttons - row 1
        actions1 = QHBoxLayout()
        actions1.setSpacing(T.PAD_SM)

        check_btn = QPushButton("Check Updates")
        check_btn.setProperty("class", "accent")
        check_btn.setFixedHeight(34)
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self._check_updates)
        actions1.addWidget(check_btn)

        dl_from_btn = QPushButton("Download From...")
        dl_from_btn.setFixedHeight(34)
        dl_from_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dl_from_btn.clicked.connect(self._download_from_chapter)
        actions1.addWidget(dl_from_btn)

        dl_all_btn = QPushButton("Download All")
        dl_all_btn.setFixedHeight(34)
        dl_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dl_all_btn.clicked.connect(self._download_all)
        actions1.addWidget(dl_all_btn)

        actions1.addStretch()
        info_layout.addLayout(actions1)

        # Action buttons - row 2
        actions2 = QHBoxLayout()
        actions2.setSpacing(T.PAD_SM)

        edit_btn = QPushButton("Edit Manga")
        edit_btn.setFixedHeight(34)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(self._show_edit_form)
        actions2.addWidget(edit_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("class", "danger")
        remove_btn.setFixedHeight(34)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._confirm_remove)
        actions2.addWidget(remove_btn)

        actions2.addStretch()
        info_layout.addLayout(actions2)

        main_row.addLayout(info_layout, 1)

        main_wrapper = QWidget()
        main_wrapper.setLayout(main_row)
        self._layout.addWidget(main_wrapper)

        # ── Edit form (hidden by default) ──
        self._edit_frame = QFrame()
        self._edit_frame.setProperty("class", "card")
        edit_inner = QVBoxLayout(self._edit_frame)
        edit_inner.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD_LG)
        edit_inner.setSpacing(T.PAD_SM)

        edit_title_lbl = QLabel("Edit Manga")
        edit_title_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        edit_inner.addWidget(edit_title_lbl)

        edit_inner.addWidget(QLabel("Title:"))
        self._edit_title = QLineEdit(title)
        self._edit_title.setFixedHeight(32)
        edit_inner.addWidget(self._edit_title)

        edit_inner.addWidget(QLabel("Primary URL:"))
        self._edit_url = QLineEdit(primary_url)
        self._edit_url.setFixedHeight(32)
        edit_inner.addWidget(self._edit_url)

        edit_inner.addWidget(QLabel("Backup URL (leave empty to remove):"))
        self._edit_backup = QLineEdit(backup_url)
        self._edit_backup.setFixedHeight(32)
        edit_inner.addWidget(self._edit_backup)

        # Fallback delay — only meaningful with a backup source, but always
        # rendered so users can fill it in alongside adding a backup. Saved
        # only when a backup URL is present (matches Add Manga behavior).
        delay_row = QHBoxLayout()
        delay_lbl = QLabel("Fallback delay (days):")
        delay_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        delay_row.addWidget(delay_lbl)
        self._edit_delay = QLineEdit(str(manga.get("fallback_delay_days", 2)))
        self._edit_delay.setFixedWidth(60)
        self._edit_delay.setFixedHeight(28)
        delay_row.addWidget(self._edit_delay)
        delay_row.addStretch()
        edit_inner.addLayout(delay_row)

        edit_btns = QHBoxLayout()
        save_edit_btn = QPushButton("Save Changes")
        save_edit_btn.setProperty("class", "accent")
        save_edit_btn.setFixedHeight(34)
        save_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_edit_btn.clicked.connect(self._save_edit)
        edit_btns.addWidget(save_edit_btn)

        cancel_edit_btn = QPushButton("Cancel")
        cancel_edit_btn.setFixedHeight(34)
        cancel_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_edit_btn.clicked.connect(self._hide_edit_form)
        edit_btns.addWidget(cancel_edit_btn)

        edit_btns.addStretch()
        edit_inner.addLayout(edit_btns)

        self._edit_frame.setVisible(False)
        self._layout.addWidget(self._edit_frame)

        # ── Chapter list section ──
        # Wrapped in a refreshable container so individual per-chapter
        # downloads (manual mode) can flip a row from Download → Read
        # without rebuilding the whole detail page.
        self._layout.addSpacing(T.PAD_MD)
        self._chapters_container = QWidget()
        chapters_layout = QVBoxLayout(self._chapters_container)
        chapters_layout.setContentsMargins(0, 0, 0, 0)
        chapters_layout.setSpacing(0)
        self._layout.addWidget(self._chapters_container)
        self._build_chapter_list()

        self._layout.addStretch()

    def _build_chapter_list(self):
        """Render the merged chapter list (downloaded + available).

        - Each row: "Chapter N" + Read button (if downloaded) OR Download button.
        - Sorted descending by numeric chapter number.
        - Falls back to a downloaded-only render when no available_chapters
          are cached yet (e.g. legacy auto manga that haven't been re-checked).
        """
        if not self._chapters_container or not self._manga:
            return

        # Reset the container layout
        layout = self._chapters_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())
        # Forget any stale download-button references
        self._pending_downloads.clear()

        title = self._manga.get("title", "")
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        available = self.app.app_state.get_available_chapters(title)
        external = self.app.app_state.get_external_chapters(title)

        # Build the merged set, keyed by chapter number string.
        # Available entries provide source/url metadata; downloaded entries
        # without metadata are still rendered (just no Download button is
        # needed because they're already on disk).
        merged: dict = {}
        for entry in available:
            num = str(entry.get("number", ""))
            if num:
                merged[num] = entry
        for ch_num in downloaded:
            num = str(ch_num)
            if num and num not in merged:
                merged[num] = {"number": num}
        # External-only entries (user said "I'm on chapter N" but the cached
        # list hasn't been pulled yet) — render them too so the user sees the
        # state was recorded. They'll get proper source metadata once a check
        # populates available_chapters.
        for ch_num in external:
            num = str(ch_num)
            if num and num not in merged:
                merged[num] = {"number": num}

        if not merged:
            empty = QLabel(
                "No chapters yet. Use 'Check Updates' to see what's available."
            )
            empty.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
            layout.addWidget(empty)
            return

        # Header
        n_dl = len(downloaded)
        n_total = len(merged)
        header = QLabel(f"Chapters ({n_dl} downloaded · {n_total} total)")
        header.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        layout.addWidget(header)
        layout.addSpacing(T.PAD_SM)

        def _sort_key(num: str) -> float:
            try:
                return float(num)
            except (ValueError, TypeError):
                return 0.0

        # Sort descending so newest chapters appear first
        for num in sorted(merged.keys(), key=_sort_key, reverse=True):
            entry = merged[num]
            ch_frame = QFrame()
            ch_frame.setProperty("class", "card")
            ch_frame.setFixedHeight(40)
            ch_row = QHBoxLayout(ch_frame)
            ch_row.setContentsMargins(T.PAD_MD, 0, T.PAD_MD, 0)

            label_text = f"Chapter {num}"
            ch_title = (entry.get("title") or "").strip()
            if ch_title and ch_title != num:
                label_text = f"Chapter {num} — {ch_title}"
            ch_label = QLabel(label_text)
            ch_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
            ch_row.addWidget(ch_label, 1)

            is_dl = self.app.app_state.is_chapter_downloaded(title, num)
            is_external = (
                not is_dl
                and self.app.app_state.is_external_chapter(title, num)
            )

            if is_dl:
                btn = QPushButton("Read")
                btn.setProperty("class", "accent")
                btn.setFixedSize(70, 26)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda checked=False, c=num: self._read_chapter(c)
                )
                ch_row.addWidget(btn)
            elif is_external:
                # Greyed "Read elsewhere" pill + Download still available
                # so the user can grab a copy if they want one on disk.
                ext_lbl = QLabel("Read elsewhere")
                ext_lbl.setStyleSheet(
                    f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};"
                )
                ch_row.addWidget(ext_lbl)
                btn = QPushButton("Download")
                btn.setFixedSize(90, 26)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda checked=False, e=entry, b=btn: self._download_chapter(e, b)
                )
                ch_row.addWidget(btn)
            else:
                btn = QPushButton("Download")
                btn.setFixedSize(90, 26)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                # Capture entry by value so the closure stays correct
                btn.clicked.connect(
                    lambda checked=False, e=entry, b=btn: self._download_chapter(e, b)
                )
                ch_row.addWidget(btn)

            layout.addWidget(ch_frame)

    def _refresh_chapter_list(self):
        """Public helper to rebuild the chapter list (used after mode change /
        download completion)."""
        self._build_chapter_list()

    # ── Status ──

    def _on_kindle_toggle(self, state):
        if not self._manga:
            return
        val = self._kindle_check.isChecked()
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["send_to_kindle"] = val
                self._manga = m
                break
        self.app.config.save()
        kind = "info" if val else "warning"
        msg = "Kindle delivery enabled" if val else "Kindle delivery disabled"
        Toast(self, msg, kind=kind)

    def _on_status_change(self, new_status):
        if not self._manga:
            return
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["status"] = new_status
                self._manga = m
                break
        self.app.config.save()
        Toast(self, f"Status: {new_status}", kind="info")

    # ── Mode (Auto / Manual) ──

    def _on_mode_change(self, label: str):
        """Persist the new mode for the current manga."""
        if not self._manga:
            return
        new_mode = "manual" if label == "Manual" else "auto"
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["mode"] = new_mode
                self._manga = m
                break
        self.app.config.set("manga", manga_list)
        self.app.config.save()

        # Update the inline hint text
        if hasattr(self, "_mode_hint") and self._mode_hint:
            self._mode_hint.setText(
                "(Manual: download chapters individually below)"
                if new_mode == "manual"
                else "(Auto: new chapters download after each check)"
            )

        Toast(
            self,
            "Mode: Manual — chapters won't auto-download"
            if new_mode == "manual"
            else "Mode: Auto — new chapters will download on next check",
            kind="info",
        )

    # ── Edit ──

    def _show_edit_form(self):
        if not self._editing:
            self._edit_frame.setVisible(True)
            self._editing = True

    def _hide_edit_form(self):
        self._edit_frame.setVisible(False)
        self._editing = False

    def _save_edit(self):
        if not self._manga:
            return

        new_title = self._edit_title.text().strip()
        new_url = self._edit_url.text().strip()
        new_backup = self._edit_backup.text().strip()
        old_title = self._manga.get("title", "")

        if not new_title:
            Toast(self, "Title cannot be empty", kind="error")
            return

        # Fallback delay — only meaningful with a backup source. Drop the
        # field entirely when the user removes the backup so config stays clean.
        try:
            new_delay = int(self._edit_delay.text().strip())
            if new_delay < 0:
                new_delay = 2
        except (ValueError, AttributeError):
            new_delay = 2

        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == old_title:
                m["title"] = new_title

                if new_url:
                    new_domain = urlparse(new_url).netloc.replace("www.", "")
                    if new_backup:
                        backup_domain = urlparse(new_backup).netloc.replace("www.", "")
                        m.pop("source", None)
                        m.pop("url", None)
                        m["sources"] = [
                            {"url": new_url, "source": new_domain},
                            {"url": new_backup, "source": backup_domain},
                        ]
                    elif "sources" in m:
                        m["sources"][0] = {"url": new_url, "source": new_domain}
                        if not new_backup and len(m.get("sources", [])) > 1:
                            m["sources"] = [m["sources"][0]]
                    else:
                        m["source"] = new_domain
                        m["url"] = new_url

                if new_backup:
                    m["fallback_delay_days"] = new_delay
                else:
                    m.pop("fallback_delay_days", None)

                if new_title != old_title:
                    old_state = self.app.app_state.get_manga_state(old_title)
                    if old_state:
                        self.app.app_state._data.setdefault("manga", {})[new_title] = old_state
                        self.app.app_state.remove_manga(old_title)

                self._manga = m
                break

        self.app.config.save()
        self._editing = False
        Toast(self, "Manga updated", kind="success")
        self._rebuild()

    # ── Downloads ──

    def _check_updates(self):
        if not self._manga:
            return
        self.app.worker.check_updates([self._manga], self.app.app_state, self.app.config)
        # For auto-mode manga we follow the user to the Downloads page since
        # something will start queueing. For manual mode we stay put — the
        # Detail page will refresh its chapter list when check_complete fires.
        mode = self._manga.get("mode", "auto")
        if mode == "auto":
            self.app.show_page("downloads")
        Toast(self, "Checking for updates...", kind="info")

    def _download_from_chapter(self):
        if not self._manga:
            return
        InputDialog(
            self, title="Download From Chapter",
            prompt="Enter chapter number to start from (0 for all):",
            default="1",
            on_submit=self._do_download_from,
        )

    def _do_download_from(self, value):
        if not value:
            return
        try:
            from_ch = float(value)
        except ValueError:
            Toast(self, "Invalid chapter number", kind="error")
            return

        title = self._manga.get("title", "")
        self.app.app_state.reset_manga_progress(title, from_ch)

        self.app.worker.check_updates([self._manga], self.app.app_state, self.app.config)
        self.app.show_page("downloads")
        ch_display = int(from_ch) if from_ch == int(from_ch) else from_ch
        Toast(self, f"Downloading from chapter {ch_display}...", kind="info")

    def _download_all(self):
        self._do_download_from("0")

    # ── Remove ──

    def _confirm_remove(self):
        if not self._manga:
            return
        title = self._manga.get("title", "Unknown")
        ConfirmDialog(
            self, title="Remove Manga",
            message=f"Remove '{title}' from your library?\nThis also removes download history.",
            on_confirm=self._do_remove,
        )

    def _do_remove(self):
        title = self._manga.get("title", "")
        manga_list = self.app.config.get("manga", [])
        manga_list = [m for m in manga_list if m.get("title") != title]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self.app.app_state.remove_manga(title)
        self.app.show_page("library")

    # ── Reader ──

    def _read_chapter(self, chapter_num):
        self.app.show_page("reader", manga=self._manga, chapter=chapter_num)

    # ── Per-chapter manual download ──

    def _download_chapter(self, ch_dict: dict, button=None):
        """Queue a single chapter for download (manual-mode flow).

        Reconstructs a ``ChapterWithSource`` from the cached entry and routes
        through the existing ``BackgroundWorker.download_chapter`` API — same
        2-concurrent queue, same Kindle delivery, same progress events.
        """
        if not self._manga:
            return

        try:
            from ...downloader import ChapterWithSource
            from ...scrapers.base import Chapter
        except Exception as e:
            Toast(self, f"Download unavailable: {e}", kind="error")
            return

        number = str(ch_dict.get("number", ""))
        if not number:
            Toast(self, "Chapter number missing", kind="error")
            return

        url = ch_dict.get("url") or ch_dict.get("source_url") or ""
        source = ch_dict.get("source", "")
        source_url = ch_dict.get("source_url") or url
        is_backup = bool(ch_dict.get("is_backup", False))
        ch_title = ch_dict.get("title") or ""

        if not url:
            Toast(self, "Chapter URL missing — re-run Check Updates", kind="error")
            return

        # Build a Chapter (then promote to ChapterWithSource for source routing)
        base = Chapter(number=number, title=ch_title, url=url, date=None)
        chapter = ChapterWithSource(base, source, source_url, is_backup=is_backup)

        # Optional Kindle delivery, same gating as the auto-queue path
        kindle_cfg = None
        global_email_on = (
            self.app.config.delivery_mode == "email" and self.app.config.email_enabled
        )
        if global_email_on and self._manga.get("send_to_kindle", True):
            try:
                from ...config import get_app_password
                kindle_cfg = {
                    "kindle_email": self.app.config.get("email.kindle_email"),
                    "sender_email": self.app.config.get("email.sender_email"),
                    "app_password": get_app_password(self.app.config),
                    "smtp_server": self.app.config.get("email.smtp_server", "smtp.gmail.com"),
                    "smtp_port": self.app.config.get("email.smtp_port", 587),
                }
            except Exception:
                kindle_cfg = None

        naming_template = self.app.config.get("delivery.naming_template")

        self.app.worker.download_chapter(
            manga=self._manga, chapter=chapter,
            output_dir=self.app.config.download_dir,
            output_format=self.app.config.output_format,
            state=self.app.app_state, kindle_cfg=kindle_cfg,
            naming_template=naming_template,
        )

        # Visual feedback: disable the button and relabel until completion
        if button is not None:
            button.setEnabled(False)
            button.setText("Queued")
            self._pending_downloads[f"{self._manga['title']}:{number}"] = button

        Toast(self, f"Queued Chapter {number}", kind="info")

    def _on_any_download_complete(self, data):
        """Refresh the chapter list when a download for the current manga
        finishes — flips the matching row from Download → Read."""
        if not self._manga:
            return
        if data.get("title") != self._manga.get("title"):
            return
        # Drop the pending button reference (the row will be rebuilt anyway)
        self._pending_downloads.pop(data.get("task_id", ""), None)
        # Only refresh if this page is currently visible to avoid wasted work
        if self.isVisible():
            self._refresh_chapter_list()

    def _on_any_check_complete(self, data):
        """Refresh the chapter list after a check completes — newly discovered
        chapters appear as Download rows without requiring navigation."""
        if not self._manga or not self.isVisible():
            return
        my_title = self._manga.get("title", "")
        for r in data.get("results", []):
            if r.get("manga", {}).get("title") == my_title:
                self._refresh_chapter_list()
                return
