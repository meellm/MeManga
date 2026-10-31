"""Settings > Advanced: reader, network and privacy, scheduled checks,
partial chapters, post-processing, import/export and diagnostics. The
actions behind its buttons run on the page."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox,
)

from ... import theme as T

# Shown instead of installing a scheduled check from the desktop app
# (issues #324, #336).
SCHEDULING_UNAVAILABLE_TEXT = (
    "Scheduled checks can't be set up from the desktop app: it has no "
    "command-line part to run them in the background. To check daily, "
    "install the MeManga command-line version and run "
    "\"memanga cron install\" (see Scheduling Automatic Checks in the "
    "guide). Remove and Status still work for a check set up earlier."
)


class AdvancedTabMixin:
    """Builds the Advanced tab into ``self._advanced_layout`` and keeps
    its hint, enabled states and cache size label current."""

    def _build_advanced(self):
        f = self._advanced_layout

        # Reader prefetch (issue #107)
        self._section(f, "Reader")
        prefetch_hint = QLabel(
            "While reading a manual-mode manga, download the next chapter "
            "in the background so Next continues without leaving the reader."
        )
        prefetch_hint.setProperty("role", "hint")
        prefetch_hint.setWordWrap(True)
        f.addWidget(prefetch_hint)

        self._prefetch_check = QCheckBox("Prefetch the next chapter while reading")
        self._prefetch_check.setChecked(self.app.config.reader_prefetch_enabled)
        f.addWidget(self._prefetch_check)

        # Remove chapters after reading (issue #104)
        remove_read_hint = QLabel(
            "Delete a chapter's local download once you finish it in the "
            "built-in reader. Read progress is kept, so the chapter simply "
            "returns to the Download state on the Detail page."
        )
        remove_read_hint.setProperty("role", "hint")
        remove_read_hint.setWordWrap(True)
        f.addWidget(remove_read_hint)

        self._remove_after_read_check = QCheckBox(
            "Remove chapters after reading"
        )
        self._remove_after_read_check.setChecked(
            self.app.config.get("reader.remove_after_read", False)
        )
        f.addWidget(self._remove_after_read_check)

        f.addSpacing(T.PAD_XL)

        # Network & Privacy (issue #337)
        self._section(f, "Network & Privacy")
        self._network_hint = QLabel(self._network_hint_text())
        # Entries come from a hand-edited file: never render them as HTML.
        self._network_hint.setTextFormat(Qt.TextFormat.PlainText)
        self._network_hint.setProperty("role", "hint")
        self._network_hint.setWordWrap(True)
        f.addWidget(self._network_hint)

        self._network_check = QCheckBox("Check the internet connection")
        self._network_check.setChecked(
            bool(self.app.config.get("gui.network_check", True))
        )
        f.addWidget(self._network_check)

        cover_hint = QLabel(
            "Search MangaDex by title for covers a source doesn't provide "
            "or that no longer load. Never used while MangaDex is turned "
            "off in Sources."
        )
        cover_hint.setProperty("role", "hint")
        cover_hint.setWordWrap(True)
        f.addWidget(cover_hint)

        self._mangadex_cover_check = QCheckBox("Find missing covers on MangaDex")
        self._mangadex_cover_check.setChecked(
            bool(self.app.config.get("gui.mangadex_cover_fallback", True))
        )
        f.addWidget(self._mangadex_cover_check)

        f.addSpacing(T.PAD_XL)

        # Scheduled checks
        self._section(f, "Scheduled Checks")
        self._cron_unavailable_hint = QLabel(SCHEDULING_UNAVAILABLE_TEXT)
        self._cron_unavailable_hint.setProperty("role", "hint")
        self._cron_unavailable_hint.setWordWrap(True)
        f.addWidget(self._cron_unavailable_hint)

        cron_row = QHBoxLayout()

        self._cron_check = QCheckBox("Enable daily auto-check")
        self._cron_check.setChecked(self.app.config.get("cron.enabled", False))
        cron_row.addWidget(self._cron_check)

        time_lbl = QLabel("Time:")
        time_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        cron_row.addWidget(time_lbl)

        self._cron_time = QLineEdit(self.app.config.get("cron.time", "06:00"))
        self._cron_time.setMinimumWidth(90)
        self._cron_time.setMaximumWidth(120)
        self._cron_time.setStyleSheet("font-family: 'Geist Mono', monospace;")
        cron_row.addWidget(self._cron_time)
        cron_row.addStretch()
        f.addLayout(cron_row)

        cron_btns = QHBoxLayout()
        install_btn = QPushButton("Install")
        install_btn.setProperty("class", "accent")
        install_btn.setMinimumHeight(36)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self._install_cron)
        cron_btns.addWidget(install_btn)
        self._cron_install_btn = install_btn

        remove_btn = QPushButton("Remove")
        remove_btn.setMinimumHeight(36)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._remove_cron)
        cron_btns.addWidget(remove_btn)
        self._cron_remove_btn = remove_btn

        status_btn = QPushButton("Status")
        status_btn.setMinimumHeight(36)
        status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        status_btn.clicked.connect(self._check_cron_status)
        cron_btns.addWidget(status_btn)
        self._cron_status_btn = status_btn

        cron_btns.addStretch()
        f.addLayout(cron_btns)

        self._cron_status_label = QLabel("")
        self._cron_status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        f.addWidget(self._cron_status_label)
        self._apply_scheduling_capability()

        f.addSpacing(T.PAD_XL)

        # Partial-chapter tolerance (issue #86)
        self._section(f, "Partial Chapters")
        partial_hint = QLabel(
            "Keep a chapter that is missing a few pages instead of discarding it."
        )
        partial_hint.setProperty("role", "hint")
        partial_hint.setWordWrap(True)
        f.addWidget(partial_hint)

        self._partial_check = QCheckBox("Allow partial chapters")
        self._partial_check.setChecked(self.app.config.partial_enabled)
        f.addWidget(self._partial_check)

        thresh_row = QHBoxLayout()
        thresh_lbl = QLabel("Max pages allowed to fail:")
        thresh_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        thresh_row.addWidget(thresh_lbl)

        self._partial_threshold = QSpinBox()
        self._partial_threshold.setMinimum(0)
        self._partial_threshold.setMaximum(100)
        self._partial_threshold.setSuffix(" %")
        self._partial_threshold.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._partial_threshold.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._partial_threshold.setValue(int(round(self.app.config.partial_threshold)))
        self._partial_threshold.setMinimumWidth(56)
        self._partial_threshold.setMaximumWidth(72)
        thresh_row.addWidget(self._partial_threshold)
        thresh_row.addStretch(1)
        f.addLayout(thresh_row)

        # Grey out the threshold when tolerance is off.
        self._partial_threshold.setEnabled(self._partial_check.isChecked())
        self._partial_check.toggled.connect(self._partial_threshold.setEnabled)

        f.addSpacing(T.PAD_XL)

        # Post-processing
        self._section(f, "Post-Processing")

        self._post_processing_check = QCheckBox("Run a command after each chapter download")
        self._post_processing_check.setChecked(
            self.app.config.get("delivery.post_processing.enabled", False)
        )
        self._post_processing_check.toggled.connect(
            self._refresh_post_processing_enabled
        )
        f.addWidget(self._post_processing_check)

        command_row = QHBoxLayout()
        command_lbl = QLabel("Command:")
        command_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        command_row.addWidget(command_lbl)

        self._post_processing_command = QLineEdit(
            self.app.config.get("delivery.post_processing.command", "")
        )
        self._post_processing_command.setMinimumHeight(36)
        self._post_processing_command.setMinimumWidth(280)
        self._post_processing_command.setPlaceholderText(
            "python scripts/after_download.py {output_path}"
        )
        command_row.addWidget(self._post_processing_command, 1)
        f.addLayout(command_row)
        self._post_processing_command.setToolTip(
            "Runs after the final chapter file or folder is created"
        )

        self._post_processing_fail_check = QCheckBox(
            "Mark download failed if the command exits with an error"
        )
        self._post_processing_fail_check.setChecked(
            self.app.config.get("delivery.post_processing.fail_on_error", False)
        )
        f.addWidget(self._post_processing_fail_check)

        pp_hint = QLabel(
            "Available placeholders: {output_path}, {title}, {chapter}, "
            "{source}, {format}, {is_dir}. The same values are also exposed "
            "as MEMANGA_* environment variables.\nCommands run directly; invoke "
            "a shell explicitly if you need shell features."
        )
        pp_hint.setWordWrap(True)
        pp_hint.setProperty("role", "hint")
        f.addWidget(pp_hint)
        self._refresh_post_processing_enabled()

        f.addSpacing(T.PAD_XL)

        # Import/Export
        self._section(f, "Import / Export")
        ie_row = QHBoxLayout()

        export_btn = QPushButton("Export")
        export_btn.setMinimumHeight(36)
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self._export)
        ie_row.addWidget(export_btn)

        import_merge_btn = QPushButton("Import (Merge)")
        import_merge_btn.setMinimumHeight(36)
        import_merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_merge_btn.clicked.connect(lambda: self._import(replace=False))
        ie_row.addWidget(import_merge_btn)

        import_replace_btn = QPushButton("Import (Replace)")
        import_replace_btn.setProperty("class", "danger")
        import_replace_btn.setMinimumHeight(36)
        import_replace_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_replace_btn.clicked.connect(lambda: self._import(replace=True))
        ie_row.addWidget(import_replace_btn)

        ie_row.addStretch()
        f.addLayout(ie_row)

        # ── Diagnostics section ──
        f.addSpacing(T.PAD_XL)
        self._section(f, "Diagnostics")

        diag_row = QHBoxLayout()

        # Clear cache — wipes the cover cache + on-disk thumbs.
        self._clear_cache_btn = QPushButton("Clear cache")
        self._clear_cache_btn.setMinimumHeight(36)
        self._clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_cache_btn.clicked.connect(self._clear_cache)
        diag_row.addWidget(self._clear_cache_btn)

        open_logs_btn = QPushButton("Open logs folder")
        open_logs_btn.setMinimumHeight(36)
        open_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_logs_btn.clicked.connect(self._open_logs_folder)
        diag_row.addWidget(open_logs_btn)

        # Cache size label, updated lazily.
        self._cache_size_label = QLabel("")
        self._cache_size_label.setProperty("role", "hint")
        diag_row.addWidget(self._cache_size_label)

        diag_row.addStretch()
        f.addLayout(diag_row)

        # Refresh cache size on display.
        QTimer.singleShot(100, self._refresh_cache_size)

    def _network_hint_text(self) -> str:
        """The connection-check hint for the hosts in the current config
        (issue #337). Rebuilt on reload so it never names stale hosts."""
        from ...network_status import configured_endpoints, invalid_hosts
        endpoints = configured_endpoints(self.app.config)
        if endpoints:
            hosts = ", ".join(f"{host}:{port}" for host, port in endpoints)
            probe_text = (
                "Every 30 seconds, open a connection (no data sent) to the "
                f"first reachable of {hosts} to notice when you go offline. "
                "When off, offline detection is off too."
            )
        else:
            probe_text = (
                "gui.network_check_hosts has no valid host, so no "
                "connection check is sent and offline detection is off."
            )
        bad_hosts = invalid_hosts(self.app.config)
        if bad_hosts:
            probe_text += (
                " Ignored entries that are not host:port: "
                + ", ".join(str(h) for h in bad_hosts) + "."
            )
        return (probe_text + " Set your own hosts with "
                "gui.network_check_hosts in config.yaml (used after a "
                "restart).")

    def _refresh_post_processing_enabled(self):
        enabled = self._post_processing_check.isChecked()
        self._post_processing_command.setEnabled(enabled)
        self._post_processing_fail_check.setEnabled(enabled)

    def _refresh_cache_size(self):
        """Compute the on-disk size of the cover cache and update the label."""
        from pathlib import Path
        cache_dir = self.app.config.config_dir / "covers"
        total = 0
        try:
            if cache_dir.exists():
                for f in cache_dir.iterdir():
                    if f.is_file():
                        total += f.stat().st_size
        except Exception:
            pass
        mb = total / (1024 * 1024)
        if mb >= 1:
            self._cache_size_label.setText(f"{mb:.1f} MB cached")
            self._clear_cache_btn.setText(f"Clear {mb:.0f} MB")
        elif total > 0:
            kb = total / 1024
            self._cache_size_label.setText(f"{kb:.0f} KB cached")
            self._clear_cache_btn.setText("Clear cache")
        else:
            self._cache_size_label.setText("Cache is empty")
            self._clear_cache_btn.setText("Clear cache")
