"""
Settings page - Tabbed: General, Email, Sources, Advanced.
"""

import json
import platform
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QComboBox, QCheckBox, QRadioButton,
    QLineEdit, QFileDialog, QButtonGroup,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T
from ..components.toast import Toast


class SettingsPage(BasePage):
    """Tabbed settings: General, Email, Sources, Advanced."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._current_tab = "general"
        self._build()

    def _build(self):
        from PySide6.QtWidgets import QFrame
        from ..assets.icons import icon
        from ... import __version__

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Page header (matches all other pages) ──
        header_w = QWidget()
        h_layout = QVBoxLayout(header_w)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Settings")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)

        reset_btn = QPushButton("  Reset to defaults")
        reset_btn.setProperty("variant", "ghost")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setIcon(icon("refresh", T.tokens()["text.t_2"], 14))
        reset_btn.setToolTip("Not implemented — see NOT_IMPLEMENTED.md")
        top_row.addWidget(reset_btn)
        h_layout.addLayout(top_row)

        meta = QLabel(f"MeManga v{__version__}  ·  Config: ~/.memanga/config.toml")
        meta.setProperty("role", "meta")
        h_layout.addWidget(meta)
        root.addWidget(header_w)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── Body: 2-col layout [200px left-rail nav] [1fr content] ──
        body_w = QWidget()
        body_l = QHBoxLayout(body_w)
        body_l.setContentsMargins(32, 20, 32, 20)
        body_l.setSpacing(24)
        root.addWidget(body_w, 1)

        # Left-rail nav (replaces the old horizontal tabs).
        nav_w = QWidget()
        nav_w.setFixedWidth(200)
        nav_l = QVBoxLayout(nav_w)
        nav_l.setContentsMargins(0, 0, 0, 0)
        nav_l.setSpacing(2)
        nav_l.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._tab_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("general",  "General",        "settings"),
            ("email",    "Kindle / Email", "bell"),
            ("advanced", "Advanced",       "refresh"),
        ]
        for key, label, icon_name in nav_items:
            btn = QPushButton("  " + label)
            btn.setProperty("variant", "nav")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setIcon(icon(icon_name, T.tokens()["text.t_2"], 16))
            from PySide6.QtCore import QSize
            btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _, t=key: self._switch_tab(t))
            nav_l.addWidget(btn)
            self._tab_buttons[key] = btn
        body_l.addWidget(nav_w)

        # Right pane: scrollable card area
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)
        body_l.addWidget(right_w, 1)

        # ── General tab ──
        self._general_scroll = QScrollArea()
        self._general_scroll.setWidgetResizable(True)
        self._general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        general_content = QWidget()
        self._general_layout = QVBoxLayout(general_content)
        self._general_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._general_layout.setSpacing(T.PAD_SM)
        self._general_scroll.setWidget(general_content)
        self._build_general()

        # ── Email tab ──
        self._email_scroll = QScrollArea()
        self._email_scroll.setWidgetResizable(True)
        self._email_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        email_content = QWidget()
        self._email_layout = QVBoxLayout(email_content)
        self._email_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._email_layout.setSpacing(T.PAD_SM)
        self._email_scroll.setWidget(email_content)
        self._build_email()

        # ── Advanced tab ──
        self._advanced_scroll = QScrollArea()
        self._advanced_scroll.setWidgetResizable(True)
        self._advanced_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        advanced_content = QWidget()
        self._advanced_layout = QVBoxLayout(advanced_content)
        self._advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._advanced_layout.setSpacing(T.PAD_SM)
        self._advanced_scroll.setWidget(advanced_content)
        self._build_advanced()

        # Add all tab scrolls into the right pane
        right_l.addWidget(self._general_scroll, 1)
        right_l.addWidget(self._email_scroll, 1)
        right_l.addWidget(self._advanced_scroll, 1)

        # Sticky save bar pinned to the bottom of the right pane — outside
        # every scroll area so it stays visible no matter how tall the
        # content is. Matches HTML spec settings.general.sticky_save_bar.
        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        self._save_bar = QFrame()
        sb_l = QHBoxLayout(self._save_bar)
        sb_l.setContentsMargins(16, 12, 16, 12)
        sb_l.setSpacing(8)
        sb_l.addStretch(1)
        self._save_bar_btn = QPushButton("Save settings")
        self._save_bar_btn.setProperty("variant", "primary")
        self._save_bar_btn.setMinimumHeight(36)
        self._save_bar_btn.setMinimumWidth(170)
        self._save_bar_btn.setIcon(_ic("check", T.tokens()["accent.on_primary"], 14))
        self._save_bar_btn.setIconSize(QSize(14, 14))
        self._save_bar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_bar_btn.clicked.connect(self._save)
        sb_l.addWidget(self._save_bar_btn)
        right_l.addWidget(self._save_bar)

        # Theme-reactive styling — without these subscriptions the
        # bar's bg + primary button kept their light/dark snapshot from
        # construct time and never refreshed.
        self._restyle_save_bar()
        T.on_theme_change(self._restyle_save_bar)

        self._switch_tab("general")

    def _restyle_save_bar(self):
        """Re-apply theme-derived inline styles to the sticky save bar.

        Bar bg + border + primary button colors all read tokens fresh,
        so flipping themes from Settings → Appearance reaches them.
        """
        from ..assets.icons import icon as _ic
        if not hasattr(self, "_save_bar"):
            return
        toks = T.tokens()
        self._save_bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {toks['surfaces.bg_0']};"
            f"  border-top: 1px solid {toks['surfaces.border']};"
            f"}}"
        )
        # Primary button — explicit stylesheet so frameless parents
        # (when the page is reparented) still render the accent fill.
        self._save_bar_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {toks['accent.primary']};"
            f"  color: {toks['accent.on_primary']};"
            f"  border: 1px solid {toks['accent.primary']};"
            f"  border-radius: 6px;"
            f"  padding: 8px 18px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {toks['accent.primary_2']};"
            f"  border-color: {toks['accent.primary_2']};"
            f"}}"
        )
        # Re-render the icon at the new on-accent color too.
        self._save_bar_btn.setIcon(_ic("check", toks["accent.on_primary"], 14))

    def _switch_tab(self, tab_name):
        self._current_tab = tab_name

        self._general_scroll.setVisible(tab_name == "general")
        self._email_scroll.setVisible(tab_name == "email")
        self._advanced_scroll.setVisible(tab_name == "advanced")

        for name, btn in self._tab_buttons.items():
            is_active = (name == tab_name)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Helpers ──

    def _section(self, parent_layout, text):
        label = QLabel(text)
        label.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        label.setContentsMargins(0, T.PAD_LG, 0, T.PAD_SM)
        parent_layout.addWidget(label)

    def _labeled_entry(self, parent_layout, label_text, value, placeholder="", password=False):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        lbl.setFixedWidth(120)
        row.addWidget(lbl)

        entry = QLineEdit()
        entry.setMinimumWidth(280)
        if placeholder:
            entry.setPlaceholderText(placeholder)
        if password:
            entry.setEchoMode(QLineEdit.EchoMode.Password)
        if value:
            entry.setText(str(value))
        row.addWidget(entry, 1)
        parent_layout.addLayout(row)
        return entry

    # ── General Tab ──

    def _build_general(self):
        f = self._general_layout

        # ── Appearance card (theme picker) ──
        # New since the spec rewrite — instantly re-themes the app via
        # the token system. Persisted in QSettings.
        from ..components.theme_picker import ThemePicker
        self._section(f, "Appearance")
        appearance_hint = QLabel("Pick a look. Affects every screen — switches instantly, no restart.")
        appearance_hint.setProperty("role", "hint")
        f.addWidget(appearance_hint)
        f.addSpacing(8)
        f.addWidget(ThemePicker())
        f.addSpacing(16)

        # Delivery mode
        self._section(f, "Delivery Mode")
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._radio_local = QRadioButton("Local (save to disk)")
        self._radio_email = QRadioButton("Email (send to Kindle)")
        self._mode_group.addButton(self._radio_local)
        self._mode_group.addButton(self._radio_email)
        if self.app.config.delivery_mode == "email":
            self._radio_email.setChecked(True)
        else:
            self._radio_local.setChecked(True)
        mode_row.addWidget(self._radio_local)
        mode_row.addSpacing(T.PAD_XL)
        mode_row.addWidget(self._radio_email)
        mode_row.addStretch()
        f.addLayout(mode_row)

        # Download directory
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("Download Directory:")
        dir_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        dir_row.addWidget(dir_lbl)

        self._dir_entry = QLineEdit(str(self.app.config.download_dir))
        self._dir_entry.setFixedHeight(30)
        self._dir_entry.setMinimumWidth(300)
        dir_row.addWidget(self._dir_entry, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(30)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        f.addLayout(dir_row)

        # Output format
        self._section(f, "Output Format")
        format_row = QHBoxLayout()
        format_row.setSpacing(12)
        self._format_combo = QComboBox()
        self._format_combo.addItems(["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"])
        self._format_combo.setCurrentText(self.app.config.output_format)
        self._format_combo.setMinimumWidth(160)
        self._format_combo.currentTextChanged.connect(lambda _: self._refresh_filename_preview())
        format_row.addWidget(self._format_combo)

        hint = QLabel("pdf/epub = e-reader  |  cbz/zip = archive")
        hint.setProperty("role", "hint")
        format_row.addWidget(hint, 1)
        f.addLayout(format_row)

        # Concurrent downloads slider (1..8).
        from PySide6.QtWidgets import QSlider
        self._section(f, "Concurrent Downloads")
        slider_row = QHBoxLayout()
        slider_row.setSpacing(14)
        slider_hint = QLabel("Higher = faster, may trip rate limits.")
        slider_hint.setProperty("role", "hint")
        slider_row.addWidget(slider_hint)

        self._concurrent_slider = QSlider(Qt.Orientation.Horizontal)
        self._concurrent_slider.setMinimum(1)
        self._concurrent_slider.setMaximum(8)
        self._concurrent_slider.setSingleStep(1)
        self._concurrent_slider.setMaximumWidth(280)
        self._concurrent_slider.setMinimumWidth(160)
        current_concurrent = int(self.app.config.get("gui.max_concurrent_downloads", 2))
        self._concurrent_slider.setValue(max(1, min(8, current_concurrent)))
        slider_row.addWidget(self._concurrent_slider)

        self._concurrent_value_lbl = QLabel(str(self._concurrent_slider.value()))
        self._concurrent_value_lbl.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 13pt; "
            f"color: {T.tokens()['accent.primary']}; min-width: 24px;"
        )
        self._concurrent_slider.valueChanged.connect(
            lambda v: self._concurrent_value_lbl.setText(str(v))
        )
        slider_row.addWidget(self._concurrent_value_lbl)
        slider_row.addStretch(1)
        f.addLayout(slider_row)

        # Naming template
        self._section(f, "File Naming")
        naming_row = QHBoxLayout()
        naming_lbl = QLabel("Template:")
        naming_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        naming_row.addWidget(naming_lbl)

        self._naming_entry = QLineEdit(
            self.app.config.get("delivery.naming_template", "{title} - Chapter {chapter}")
        )
        self._naming_entry.setFixedHeight(30)
        self._naming_entry.setMinimumWidth(280)
        self._naming_entry.textChanged.connect(self._refresh_filename_preview)
        naming_row.addWidget(self._naming_entry, 1)
        f.addLayout(naming_row)

        # Variable chips — click to insert into the template.
        var_row = QHBoxLayout()
        var_row.setSpacing(6)
        var_label = QLabel("Variables:")
        var_label.setProperty("role", "hint")
        var_row.addWidget(var_label)
        for var in ["{title}", "{chapter}", "{source}", "{date}"]:
            chip = QPushButton(var)
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, v=var: self._insert_template_var(v))
            var_row.addWidget(chip)
        var_row.addStretch(1)
        f.addLayout(var_row)

        # Live preview of resolved filename.
        self._preview_frame = QFrame()
        pf_l = QHBoxLayout(self._preview_frame)
        pf_l.setContentsMargins(12, 8, 12, 8)
        pf_l.setSpacing(8)
        pf_label = QLabel("Preview:")
        pf_label.setProperty("role", "hint")
        pf_l.addWidget(pf_label)
        self._filename_preview = QLabel("")
        pf_l.addWidget(self._filename_preview)
        pf_l.addStretch(1)
        f.addWidget(self._preview_frame)
        # Style + restyle on theme change so it isn't stuck on the
        # snapshot taken at construct time.
        self._style_preview_frame()
        T.on_theme_change(self._style_preview_frame)
        self._refresh_filename_preview()

        # Save button moved to the sticky save bar at the bottom of the
        # right pane (always visible regardless of scroll position).

    # ── Email Tab ──

    def _build_email(self):
        f = self._email_layout

        self._section(f, "Kindle / SMTP")

        self._entry_kindle_email = self._labeled_entry(
            f, "Kindle Email:", self.app.config.get("email.kindle_email", ""), "your-kindle@kindle.com"
        )
        self._entry_sender_email = self._labeled_entry(
            f, "Sender Email:", self.app.config.get("email.sender_email", ""), "your-email@gmail.com"
        )
        self._entry_smtp_server = self._labeled_entry(
            f, "SMTP Server:", self.app.config.get("email.smtp_server", "smtp.gmail.com")
        )
        self._entry_smtp_port = self._labeled_entry(
            f, "SMTP Port:", str(self.app.config.get("email.smtp_port", 587))
        )

        # Password row
        pw_row = QHBoxLayout()
        pw_lbl = QLabel("App Password:")
        pw_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        pw_lbl.setFixedWidth(120)
        pw_row.addWidget(pw_lbl)

        self._password_entry = QLineEdit()
        self._password_entry.setFixedHeight(30)
        self._password_entry.setFixedWidth(220)
        self._password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        pw_row.addWidget(self._password_entry)

        pw_hint = QLabel("(leave blank to keep)")
        pw_hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        pw_row.addWidget(pw_hint)
        pw_row.addStretch()
        f.addLayout(pw_row)

        # Delete after send
        self._delete_after_check = QCheckBox("Delete file after sending")
        self._delete_after_check.setChecked(self.app.config.get("delivery.delete_after_send", False))
        f.addWidget(self._delete_after_check)

        f.addSpacing(T.PAD_SM)

        # Test connection
        test_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.setFixedHeight(30)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.clicked.connect(self._test_email)
        test_row.addWidget(test_btn)

        self._test_label = QLabel("")
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
        test_row.addWidget(self._test_label)
        test_row.addStretch()
        f.addLayout(test_row)

        # Save button lives in the shared sticky bar at the bottom of
        # the right pane (always visible regardless of scroll position).

    # ── Advanced Tab ──

    def _build_advanced(self):
        f = self._advanced_layout

        # Scheduled checks
        self._section(f, "Scheduled Checks")
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
        install_btn.setFixedHeight(28)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self._install_cron)
        cron_btns.addWidget(install_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setFixedHeight(28)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._remove_cron)
        cron_btns.addWidget(remove_btn)

        status_btn = QPushButton("Status")
        status_btn.setFixedHeight(28)
        status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        status_btn.clicked.connect(self._check_cron_status)
        cron_btns.addWidget(status_btn)

        cron_btns.addStretch()
        f.addLayout(cron_btns)

        self._cron_status_label = QLabel("")
        self._cron_status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        f.addWidget(self._cron_status_label)

        f.addSpacing(T.PAD_XL)

        # Import/Export
        self._section(f, "Import / Export")
        ie_row = QHBoxLayout()

        export_btn = QPushButton("Export")
        export_btn.setFixedHeight(30)
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self._export)
        ie_row.addWidget(export_btn)

        import_merge_btn = QPushButton("Import (Merge)")
        import_merge_btn.setFixedHeight(30)
        import_merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_merge_btn.clicked.connect(lambda: self._import(replace=False))
        ie_row.addWidget(import_merge_btn)

        import_replace_btn = QPushButton("Import (Replace)")
        import_replace_btn.setProperty("class", "danger")
        import_replace_btn.setFixedHeight(30)
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
        self._clear_cache_btn.setFixedHeight(30)
        self._clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_cache_btn.clicked.connect(self._clear_cache)
        diag_row.addWidget(self._clear_cache_btn)

        open_logs_btn = QPushButton("Open logs folder")
        open_logs_btn.setFixedHeight(30)
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
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._refresh_cache_size)

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

    def _clear_cache(self):
        """Delete cached cover thumbnails and reset the in-memory cache."""
        from pathlib import Path
        from ..components.dialogs import ConfirmDialog
        cache_dir = self.app.config.config_dir / "covers"

        def _do_clear():
            removed = 0
            try:
                if cache_dir.exists():
                    for f in cache_dir.iterdir():
                        if f.is_file():
                            try:
                                f.unlink()
                                removed += 1
                            except Exception:
                                pass
            except Exception:
                pass
            # Reset the in-memory pixmap cache so stale entries don't linger.
            try:
                self.app.cover_cache._memory.clear()
                self.app.cover_cache._failed.clear()
            except Exception:
                pass
            Toast(self, f"Cleared {removed} cached file(s)", kind="success")
            self._refresh_cache_size()

        ConfirmDialog(
            self, title="Clear cache?",
            message="This removes all locally-cached cover thumbnails. They'll be re-fetched next time.",
            on_confirm=_do_clear,
        )

    def _open_logs_folder(self):
        """Open the user config dir (where state.json + logs live) in the
        OS file manager.
        """
        import platform, subprocess
        from pathlib import Path
        path = Path(self.app.config.config_dir)
        path.mkdir(parents=True, exist_ok=True)
        try:
            if platform.system() == "Darwin":
                subprocess.run(["open", str(path)])
            elif platform.system() == "Windows":
                subprocess.run(["explorer", str(path)])
            else:
                subprocess.run(["xdg-open", str(path)])
            Toast(self, f"Opened {path}", kind="info")
        except Exception as e:
            Toast(self, f"Couldn't open folder: {e}", kind="error")

    # ── Actions ──

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if path:
            self._dir_entry.setText(path)

    def _validate_time(self, time_str):
        try:
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                return False
            h, m = int(parts[0]), int(parts[1])
            return 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, IndexError):
            return False

    def _style_preview_frame(self):
        """Apply theme colors to the filename preview frame + its label.
        Called once at build + again on every theme switch."""
        if not hasattr(self, "_preview_frame"):
            return
        self._preview_frame.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {T.tokens()['surfaces.bg_0']};"
            f"  border: 1px dashed {T.tokens()['surfaces.border_strong']};"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._filename_preview.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 11pt;"
            f"color: {T.tokens()['accent.primary']};"
        )

    def _insert_template_var(self, var: str):
        """Insert a {variable} token at the cursor of the naming template."""
        cur = self._naming_entry.cursorPosition()
        text = self._naming_entry.text()
        new_text = text[:cur] + var + text[cur:]
        self._naming_entry.setText(new_text)
        self._naming_entry.setCursorPosition(cur + len(var))
        self._naming_entry.setFocus()

    def _refresh_filename_preview(self):
        """Render a live preview of the filename template + extension."""
        # Guard: format-combo's setCurrentText fires while the preview
        # widgets are still being built. Skip until both exist.
        if not (hasattr(self, "_naming_entry") and hasattr(self, "_filename_preview")):
            return
        template = self._naming_entry.text().strip() or "{title} - Chapter {chapter}"
        from datetime import datetime
        sample = {
            "title": "Chainsaw Man",
            "chapter": "1",
            "source": "mangadex.org",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "author": "Tatsuki Fujimoto",
            "volume": "1",
        }
        try:
            filename = template.format(**sample)
        except Exception:
            filename = template
        ext = self._format_combo.currentText() if hasattr(self, "_format_combo") else "pdf"
        # Strip leading dot if user picked the "(.pdf)" format string.
        if ext.startswith("."):
            ext = ext[1:]
        self._filename_preview.setText(f"{filename}.{ext}")

    def _save(self):
        cfg = self.app.config
        mode = "email" if self._radio_email.isChecked() else "local"
        cfg.set("delivery.mode", mode)
        cfg.set("delivery.download_dir", self._dir_entry.text().strip())
        cfg.set("delivery.output_format", self._format_combo.currentText())
        cfg.set("delivery.delete_after_send", self._delete_after_check.isChecked())
        # Concurrent downloads (slider)
        if hasattr(self, "_concurrent_slider"):
            new_concurrent = int(self._concurrent_slider.value())
            cfg.set("gui.max_concurrent_downloads", new_concurrent)
            # Push the new value into the live worker pool so it takes
            # effect immediately, without a restart.
            try:
                self.app.worker._max_concurrent_downloads = new_concurrent
            except Exception:
                pass

        template = self._naming_entry.text().strip()
        if not template or ("{title}" not in template and "{chapter}" not in template):
            template = "{title} - Chapter {chapter}"
        cfg.set("delivery.naming_template", template)

        cfg.set("email.kindle_email", self._entry_kindle_email.text().strip())
        cfg.set("email.sender_email", self._entry_sender_email.text().strip())
        cfg.set("email.smtp_server", self._entry_smtp_server.text().strip())

        port_str = self._entry_smtp_port.text().strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
            cfg.set("email.smtp_port", port)
        except ValueError:
            cfg.set("email.smtp_port", 587)

        pw = self._password_entry.text().strip()
        if pw:
            from ...config import set_app_password
            set_app_password(cfg, pw)

        cron_time = self._cron_time.text().strip()
        if not self._validate_time(cron_time):
            cron_time = "06:00"
        cfg.set("cron.enabled", self._cron_check.isChecked())
        cfg.set("cron.time", cron_time)

        cfg.save()
        Toast(self, "Settings saved", kind="success")

    def _test_email(self):
        self._test_label.setText("Testing...")
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")

        sender = self._entry_sender_email.text().strip()
        smtp_server = self._entry_smtp_server.text().strip()
        smtp_port = self._entry_smtp_port.text().strip()
        pw = self._password_entry.text().strip()

        if not sender or not smtp_server:
            self._test_label.setText("Fill sender + server")
            self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            return
        if not pw:
            from ...config import get_app_password
            pw = get_app_password(self.app.config)
        if not pw:
            self._test_label.setText("No password")
            self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            return

        def _test():
            import smtplib
            try:
                server = smtplib.SMTP(smtp_server, int(smtp_port), timeout=10)
                server.ehlo()
                server.starttls()
                server.login(sender, pw)
                server.quit()
                self._test_label.setText("Success!")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.SUCCESS};")
            except smtplib.SMTPAuthenticationError:
                self._test_label.setText("Auth failed")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            except Exception as e:
                msg = str(e)[:30]
                self._test_label.setText(f"Failed: {msg}")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")

        threading.Thread(target=_test, daemon=True).start()

    # ── Cron ──

    def _install_cron(self):
        cron_time = self._cron_time.text().strip()
        if not self._validate_time(cron_time):
            Toast(self, "Invalid time", kind="error")
            return
        hour, minute = cron_time.split(":")
        project_dir = Path(__file__).resolve().parent.parent.parent.parent

        if platform.system() == "Windows":
            self._install_cron_windows(project_dir, cron_time)
        else:
            self._install_cron_unix(project_dir, hour, minute)

    def _install_cron_unix(self, project_dir, hour, minute):
        python_path = sys.executable
        venv_python = project_dir / "venv" / "bin" / "python3"
        if venv_python.exists():
            python_path = str(venv_python)
        cron_cmd = (
            f'{minute} {hour} * * * cd {project_dir} && {python_path} '
            f'-m memanga check --auto --quiet >> {project_dir}/memanga.log 2>&1'
        )
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            lines = [line for line in existing.strip().split("\n") if line and "memanga" not in line]
            lines.append(cron_cmd)
            proc = subprocess.run(
                ["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True
            )
            if proc.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", f"{hour}:{minute}")
                self.app.config.save()
                Toast(self, f"Cron: daily at {hour}:{minute}", kind="success")
            else:
                Toast(self, f"Failed: {proc.stderr[:40]}", kind="error")
        except Exception as e:
            Toast(self, f"Error: {str(e)[:40]}", kind="error")

    def _install_cron_windows(self, project_dir, cron_time):
        python_path = sys.executable
        venv_python = project_dir / "venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            python_path = str(venv_python)
        task_name = "MeManga_AutoCheck"
        cmd = f'"{python_path}" -m memanga check --auto --quiet'
        try:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True, text=True,
            )
            result = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/SC", "DAILY",
                 "/ST", cron_time, "/TR", cmd, "/F"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", cron_time)
                self.app.config.save()
                Toast(self, f"Task: daily at {cron_time}", kind="success")
            else:
                Toast(self, f"Failed: {result.stderr[:40]}", kind="error")
        except Exception as e:
            Toast(self, f"Error: {str(e)[:40]}", kind="error")

    def _remove_cron(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", "MeManga_AutoCheck", "/F"],
                    capture_output=True, text=True,
                )
                Toast(self, "Task removed", kind="success")
            except Exception:
                Toast(self, "Failed", kind="error")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                lines = [line for line in existing.strip().split("\n") if line and "memanga" not in line]
                subprocess.run(
                    ["crontab", "-"],
                    input=("\n".join(lines) + "\n") if lines else "",
                    capture_output=True, text=True,
                )
                Toast(self, "Cron removed", kind="success")
            except Exception:
                Toast(self, "Failed", kind="error")
        self.app.config.set("cron.enabled", False)
        self.app.config.save()

    def _check_cron_status(self):
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", "MeManga_AutoCheck"],
                    capture_output=True, text=True,
                )
                text = "Task installed" if result.returncode == 0 else "No task found"
                color = T.SUCCESS if result.returncode == 0 else T.WARNING
            except Exception:
                text, color = "Check failed", T.ERROR
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                found = result.returncode == 0 and "memanga" in result.stdout
                text = "Cron installed" if found else "No cron found"
                color = T.SUCCESS if found else T.WARNING
            except Exception:
                text, color = "Check failed", T.ERROR
        self._cron_status_label.setText(text)
        self._cron_status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")

    # ── Import/Export ──

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "memanga_export.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = {
                "version": 1,
                "exported_at": datetime.now().isoformat(),
                "manga": self.app.config.get("manga", []),
                "state": self.app.app_state._data.get("manga", {}),
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            Toast(self, f"Exported {len(data['manga'])} manga", kind="success")
        except Exception as e:
            Toast(self, f"Export failed: {str(e)[:40]}", kind="error")

    def _import(self, replace=False):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            manga_list = data.get("manga", [])
            if not isinstance(manga_list, list):
                Toast(self, "Invalid file", kind="error")
                return
            if replace:
                self.app.config.set("manga", manga_list)
                self.app.config.save()
                self.app.app_state._data["manga"] = data.get("state", {})
                self.app.app_state.save()
                Toast(self, f"Replaced with {len(manga_list)} manga", kind="success")
            else:
                existing = self.app.config.get("manga", [])
                existing_titles = {m.get("title", "").lower() for m in existing}
                added = sum(
                    1 for m in manga_list if m.get("title", "").lower() not in existing_titles
                )
                for m in manga_list:
                    if m.get("title", "").lower() not in existing_titles:
                        existing.append(m)
                self.app.config.set("manga", existing)
                self.app.config.save()
                for t, sdata in data.get("state", {}).items():
                    if not self.app.app_state.get_manga_state(t):
                        self.app.app_state._data.setdefault("manga", {})[t] = sdata
                self.app.app_state.save()
                Toast(self, f"Imported {added} manga", kind="success")
        except json.JSONDecodeError:
            Toast(self, "Invalid JSON", kind="error")
        except Exception as e:
            Toast(self, f"Failed: {str(e)[:40]}", kind="error")
