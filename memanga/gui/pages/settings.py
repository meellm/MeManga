"""
Settings page - Tabbed: General, Email, Advanced, About.
"""

import json
import logging
import platform
import subprocess
import sys
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QComboBox, QCheckBox, QRadioButton,
    QLineEdit, QFileDialog, QButtonGroup, QSizePolicy, QSpinBox,
    QAbstractSpinBox,
)
from PySide6.QtCore import Qt, QEvent, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from .base import BasePage
from .. import theme as T
from ... import doctor
from ..components.error_details import detail_tooltip, notify_error, summarize_error
from ..components.toast import Toast
from ...backup import EXPORT_VERSION, BackupVersionError, validate_backup
from ...emailer import kindle_format_error
from ...cron import (build_cron_line, build_task_command, managed_lines,
                     read_crontab,
                     remove_managed_lines, replace_managed_line,
                     scheduled_checks_supported, source_checkout_root,
                     unmanaged_memanga_lines)

logger = logging.getLogger(__name__)

# Shown instead of installing a scheduled check from the desktop app
# (issues #324, #336).
SCHEDULING_UNAVAILABLE_TEXT = (
    "Scheduled checks can't be set up from the desktop app: it has no "
    "command-line part to run them in the background. To check daily, "
    "install the MeManga command-line version and run "
    "\"memanga cron install\" (see Scheduling Automatic Checks in the "
    "guide). Remove and Status still work for a check set up earlier."
)


def _kindle_format_toast_text(config):
    """Settings-saved notice when Send to Kindle is chosen with an output
    format Kindle doesn't accept (issue #362), else None. The settings
    are still saved: the format works for local downloads."""
    if config.delivery_mode != "email":
        return None
    reason = kindle_format_error(config.output_format)
    if not reason:
        return None
    return (f"{reason}\nChapters will be saved but not sent to Kindle;\n"
            "choose PDF or EPUB to send them.")


def _plaintext_password_toast_text(config_path) -> str:
    """Settings-saved notice when the app password went to config.yaml
    because no system keyring is usable (issue #247). Names the file,
    never the password."""
    return (
        "Settings saved. No system keyring is available, so the app\n"
        "password is stored in plain text in:\n"
        f"{config_path}\n"
        "Keep this file private: only your user account should be able\n"
        "to read it (on Linux and macOS: chmod 600)."
    )


class _EmailTestSignals(QObject):
    result = Signal(str, str, str)  # text, kind, full error (may be "")


class _AboutSignals(QObject):
    checked = Signal(object)  # doctor.about_checks() result


class _WrappingLabel(QLabel):
    """A word-wrapped label whose size hints carry the height its text
    needs at its current width. The tab layouts are top-aligned, which
    sizes them from sizeHint() and ignores heightForWidth(), so a long
    wrapped text would otherwise be clipped and overlap the next row.

    The hints are overridden instead of setting a minimum height:
    QLabel.heightForWidth() never returns less than minimumHeight(), so
    the height could then only grow when the label gets wider."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._text_height = 0

    def _fit_height(self) -> None:
        height = self.heightForWidth(self.width())
        if height != self._text_height:
            self._text_height = height
            self.updateGeometry()

    def _with_text_height(self, size):
        if self._text_height > 0:
            size.setHeight(self._text_height)
        return size

    def sizeHint(self):
        return self._with_text_height(super().sizeHint())

    def minimumSizeHint(self):
        return self._with_text_height(super().minimumSizeHint())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        # A style sheet can change the font after the first resize.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_height()

    def setText(self, text):
        super().setText(text)
        # A status line can change its text without changing width.
        self._fit_height()


class SettingsPage(BasePage):
    """Tabbed settings: General, Email, Sources, Advanced."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._current_tab = "general"
        self._email_test_signals = _EmailTestSignals(self)
        self._email_test_signals.result.connect(self._set_email_test_result)
        self._about_signals = _AboutSignals(self)
        self._about_signals.checked.connect(self._set_about_checks)
        self._about_info = None  # filled on the first visit to About
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
        reset_btn.setToolTip("Reset all settings to defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
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
            ("about",    "About",          "info"),
        ]
        for key, label, icon_name in nav_items:
            btn = QPushButton("  " + label)
            btn.setProperty("variant", "nav")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # 42 px — same as the sidebar nav buttons. The nav QSS
            # variant now uses 8/12/13/12 padding to keep descenders
            # ('g' in "General"/"Settings", 'l' in "Kindle / Email")
            # from clipping on Windows; the button needs the full
            # height to honour the padding.
            btn.setFixedHeight(42)
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

        # ── About tab ──
        self._about_scroll = QScrollArea()
        self._about_scroll.setWidgetResizable(True)
        self._about_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        about_content = QWidget()
        self._about_layout = QVBoxLayout(about_content)
        self._about_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._about_layout.setSpacing(T.PAD_SM)
        self._about_scroll.setWidget(about_content)
        self._build_about()

        # Add all tab scrolls into the right pane
        right_l.addWidget(self._general_scroll, 1)
        right_l.addWidget(self._email_scroll, 1)
        right_l.addWidget(self._advanced_scroll, 1)
        right_l.addWidget(self._about_scroll, 1)

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
        self._about_scroll.setVisible(tab_name == "about")
        if tab_name == "about" and self._about_info is None:
            self._start_about_checks()

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
        # Narrow enough for the Email tab to fit the 900 px minimum
        # window width; the entry still stretches when there is room.
        entry.setMinimumWidth(160)
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

        # Issue #345: which manga email delivery applies to, asked where
        # it is turned on. Preselected so turning it on never sends a
        # whole library by default.
        self._section(f, "Send to Kindle")
        scope_row = QHBoxLayout()
        self._scope_group = QButtonGroup(self)
        self._radio_scope_selected = QRadioButton("Only manga I choose")
        self._radio_scope_selected.setToolTip(
            "Turn on Send to Kindle after download on each manga's page.")
        self._radio_scope_all = QRadioButton("Every manga in my library")
        self._radio_scope_all.setToolTip(
            "Every manga is sent unless you turn Kindle off on its page.")
        self._scope_group.addButton(self._radio_scope_selected)
        self._scope_group.addButton(self._radio_scope_all)
        scope_row.addWidget(self._radio_scope_selected)
        scope_row.addSpacing(T.PAD_XL)
        scope_row.addWidget(self._radio_scope_all)
        scope_row.addStretch()
        f.addLayout(scope_row)
        self._scope_hint = _WrappingLabel(
            "Applies when Email is selected. A manga you already turned "
            "Kindle on or off for keeps that choice."
        )
        self._scope_hint.setProperty("role", "hint")
        f.addWidget(self._scope_hint)
        self._radio_email.toggled.connect(self._refresh_kindle_scope_enabled)
        self._load_kindle_scope()

        # Download directory
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("Download Directory:")
        dir_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        dir_row.addWidget(dir_lbl)

        self._dir_entry = QLineEdit(str(self.app.config.download_dir))
        self._dir_entry.setMinimumHeight(36)
        self._dir_entry.setMinimumWidth(300)
        dir_row.addWidget(self._dir_entry, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setMinimumHeight(36)
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

        hint = QLabel("pdf/epub = e-reader, Kindle  |  cbz/zip/images = local only")
        hint.setProperty("role", "hint")
        format_row.addWidget(hint, 1)
        f.addLayout(format_row)

        self._section(f, "MangaDex Image Quality")
        self._mangadex_quality = QComboBox()
        self._mangadex_quality.addItem("Original", False)
        self._mangadex_quality.addItem("Data saver (smaller downloads)", True)
        self._mangadex_quality.setCurrentIndex(
            1 if self.app.config.get("mangadex.data_saver", False) else 0)
        self._mangadex_quality.setMaximumWidth(280)
        f.addWidget(self._mangadex_quality)

        # Concurrent downloads slider (1..8). JumpSlider so a groove
        # click sets the clicked value instead of page-stepping to an
        # extreme (#46).
        from ..components.slider import JumpSlider
        self._section(f, "Concurrent Downloads")
        slider_row = QHBoxLayout()
        slider_row.setSpacing(14)
        slider_hint = QLabel("Higher = faster, may trip rate limits.")
        slider_hint.setProperty("role", "hint")
        slider_row.addWidget(slider_hint)

        self._concurrent_slider = JumpSlider(Qt.Orientation.Horizontal)
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
        self._naming_entry.setMinimumHeight(36)
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
        self._filename_preview.setWordWrap(True)
        self._filename_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        pf_l.addWidget(self._filename_preview, 1)
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
        self._password_entry.setMinimumHeight(36)
        self._password_entry.setMinimumWidth(160)
        self._password_entry.setMaximumWidth(220)
        self._password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        pw_row.addWidget(self._password_entry)

        # Wraps instead of widening the tab past a narrow window.
        pw_hint = _WrappingLabel("(leave blank to keep)")
        pw_hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        pw_row.addWidget(pw_hint, 1)
        f.addLayout(pw_row)

        # Delete after send
        self._delete_after_check = QCheckBox("Delete file after sending")
        self._delete_after_check.setChecked(self.app.config.get("delivery.delete_after_send", False))
        f.addWidget(self._delete_after_check)

        f.addSpacing(T.PAD_SM)

        # Issue #365 / #339: a quick login check, and a real test that
        # sends a tiny PDF to the Kindle address.
        self._test_hint = _WrappingLabel(
            "Check Login only signs in to the mail server and sends nothing. "
            "Send Test PDF emails a one-page PDF to the Kindle address above. "
            "If the mail server accepts it, Amazon still delivers it only "
            "when the sender is on your Approved Personal Document E-mail "
            "List, so look for it in your Kindle library after a few minutes."
        )
        self._test_hint.setProperty("role", "hint")
        f.addWidget(self._test_hint)

        test_row = QHBoxLayout()
        self._login_test_btn = QPushButton("Check Login")
        self._login_test_btn.setToolTip(
            "Log in to the SMTP server with these settings. Sends nothing.")
        self._login_test_btn.setAccessibleDescription(
            "Logs in to the SMTP server only; no email is sent.")
        self._send_test_btn = QPushButton("Send Test PDF")
        self._send_test_btn.setToolTip(
            "Email a small test PDF to the Kindle address above.")
        self._send_test_btn.setAccessibleDescription(
            "Emails a one-page test PDF to the Kindle address. Amazon "
            "delivers it only if the sender address is approved.")
        for btn, slot in ((self._login_test_btn, self._test_email),
                          (self._send_test_btn, self._send_test_email)):
            btn.setMinimumHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            test_row.addWidget(btn)

        test_row.addStretch()
        f.addLayout(test_row)

        # Its own wrapping line below the buttons, so a long result
        # stays readable in a narrow window.
        self._test_label = _WrappingLabel("")
        # Shows a server's reply: never render it as HTML.
        self._test_label.setTextFormat(Qt.TextFormat.PlainText)
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
        f.addWidget(self._test_label)

        # Save button lives in the shared sticky bar at the bottom of
        # the right pane (always visible regardless of scroll position).

    # ── Advanced Tab ──

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

    # ── About Tab ──

    def _build_about(self):
        """Version and environment for bug reports (issue #343).

        Rows start as "Checking…" for the keyring and browsers; those are
        probed off the GUI thread on the first visit to the tab.
        """
        f = self._about_layout
        self._section(f, "About")

        hint = QLabel("Version and environment details for bug reports. "
                      "Copied text leaves out folder paths, user names, "
                      "e-mail addresses and passwords.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        f.addWidget(hint)

        self._about_values: dict[str, QLabel] = {}
        for label_text, value in doctor.about_rows({}):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
            lbl.setFixedWidth(120)
            row.addWidget(lbl)

            val = QLabel(value)
            val.setTextFormat(Qt.TextFormat.PlainText)
            val.setWordWrap(True)
            val.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            row.addWidget(val, 1)
            f.addLayout(row)
            self._about_values[label_text] = val

        f.addSpacing(T.PAD_SM)
        copy_row = QHBoxLayout()
        self._copy_about_btn = QPushButton("Copy diagnostics")
        self._copy_about_btn.setMinimumHeight(36)
        self._copy_about_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_about_btn.setAccessibleDescription(
            "Copy the version and environment details to the clipboard")
        self._copy_about_btn.clicked.connect(self._copy_about)
        # Enabled once the checks report back: "Checking…" rows are not
        # worth pasting into a bug report.
        self._copy_about_btn.setEnabled(False)
        copy_row.addWidget(self._copy_about_btn)
        copy_row.addStretch()
        f.addLayout(copy_row)

    def _start_about_checks(self):
        self._about_info = doctor.about_basics()
        self._refresh_about_rows()
        signals = self._about_signals

        def _check():
            try:
                result = doctor.about_checks()
            except Exception:
                result = {}
            try:
                signals.checked.emit(result)
            except RuntimeError:
                pass  # page already closed and deleted

        threading.Thread(target=_check, daemon=True,
                         name="settings-about-checks").start()

    @Slot(object)
    def _set_about_checks(self, result):
        if self._about_info is None:
            return
        self._about_info.update(result or {
            "keyring": {"backend": None},
            "browsers": {"status": "error"},
        })
        self._refresh_about_rows()
        self._copy_about_btn.setEnabled(True)

    def _refresh_about_rows(self):
        for label_text, value in doctor.about_rows(self._about_info or {}):
            val = self._about_values.get(label_text)
            if val is not None:
                val.setText(value)
                val.setAccessibleName(f"{label_text}: {value}")

    def _copy_about(self):
        if self._about_info is None or not self._copy_about_btn.isEnabled():
            return  # checks still running
        QGuiApplication.clipboard().setText(doctor.format_about(self._about_info))
        self._copy_about_btn.setText("Copied")
        self._copy_about_btn.setAccessibleName("Copied")
        QTimer.singleShot(1500, self._reset_copy_about_label)

    def _reset_copy_about_label(self):
        try:
            self._copy_about_btn.setText("Copy diagnostics")
            self._copy_about_btn.setAccessibleName("")
        except RuntimeError:
            pass  # page already closed and deleted

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
        from .._subprocess import open_in_file_manager
        path = self.app.config.config_dir
        if open_in_file_manager(path):
            Toast(self, f"Opened {path}", kind="info")
        else:
            Toast(self, "Couldn't open the logs folder", kind="error")

    # ── Actions ──

    def _load_kindle_scope(self):
        from ...email_settings import proposed_kindle_scope
        if proposed_kindle_scope(self.app.config) == "all":
            self._radio_scope_all.setChecked(True)
        else:
            self._radio_scope_selected.setChecked(True)
        self._refresh_kindle_scope_enabled()

    def _refresh_kindle_scope_enabled(self, *_):
        email = self._radio_email.isChecked()
        self._radio_scope_selected.setEnabled(email)
        self._radio_scope_all.setEnabled(email)

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
        from ...downloader.naming import _format_chapter_number
        sample = {
            "title": "Chainsaw Man",
            # Same zero-padded form the downloader writes ("0001.000").
            "chapter": _format_chapter_number("1"),
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
        if mode == "email":
            cfg.set("email.kindle_scope",
                    "all" if self._radio_scope_all.isChecked() else "selected")
        cfg.set("delivery.download_dir", self._dir_entry.text().strip())
        cfg.set("delivery.output_format", self._format_combo.currentText())
        cfg.set("mangadex.data_saver", self._mangadex_quality.currentData())
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
        password_in_config = False
        if pw:
            from ...config import set_app_password
            password_in_config = set_app_password(cfg, pw) == "config"

        # Where scheduling is unsupported the controls are disabled and
        # may still show a value Remove has since cleared, so they never
        # write cron settings (issue #324).
        if scheduled_checks_supported():
            cron_time = self._cron_time.text().strip()
            if not self._validate_time(cron_time):
                cron_time = "06:00"
            cfg.set("cron.enabled", self._cron_check.isChecked())
            cfg.set("cron.time", cron_time)
        cfg.set(
            "delivery.post_processing.enabled",
            self._post_processing_check.isChecked(),
        )
        cfg.set(
            "delivery.post_processing.command",
            self._post_processing_command.text().strip(),
        )
        cfg.set(
            "delivery.post_processing.fail_on_error",
            self._post_processing_fail_check.isChecked(),
        )

        # Partial-chapter tolerance (issue #86)
        if hasattr(self, "_partial_check"):
            cfg.set("partial_chapters.enabled", self._partial_check.isChecked())
            cfg.set("partial_chapters.threshold_percent", int(self._partial_threshold.value()))

        # Reader prefetch (issue #107)
        if hasattr(self, "_prefetch_check"):
            cfg.set("gui.reader_prefetch_next", self._prefetch_check.isChecked())

        # Remove chapters after reading (issue #104)
        if hasattr(self, "_remove_after_read_check"):
            cfg.set(
                "reader.remove_after_read",
                self._remove_after_read_check.isChecked(),
            )

        cfg.save()
        kindle_notice = _kindle_format_toast_text(cfg)
        if password_in_config:
            # Issue #247: no keyring, so say where the password went.
            text = _plaintext_password_toast_text(cfg.config_path)
            if kindle_notice:
                text += "\n\n" + kindle_notice
            Toast(self, text, kind="warning", duration=10000)
        elif kindle_notice:
            Toast(self, "Settings saved.\n" + kindle_notice,
                  kind="warning", duration=10000)
        else:
            Toast(self, "Settings saved", kind="success")

    def _reset_to_defaults(self):
        cfg = self.app.config
        defaults = cfg._default_config()
        # A reset restores preferences, not the user's group block list.
        removed_groups = list(cfg.get("mangadex.removed_group_ids", []) or [])
        for section in ("delivery", "email", "cron", "gui", "partial_chapters",
                        "reader", "mangadex"):
            cfg.set(section, defaults[section])
        cfg.set("mangadex.removed_group_ids", removed_groups)
        cfg.save()
        self._load_config_into_widgets()
        Toast(self, "Settings reset to defaults", kind="success")

    def _load_config_into_widgets(self):
        cfg = self.app.config

        if cfg.delivery_mode == "email":
            self._radio_email.setChecked(True)
        else:
            self._radio_local.setChecked(True)
        self._load_kindle_scope()

        self._dir_entry.setText(str(cfg.download_dir))
        self._format_combo.setCurrentText(cfg.output_format)
        self._mangadex_quality.setCurrentIndex(
            1 if cfg.get("mangadex.data_saver", False) else 0)
        self._concurrent_slider.setValue(
            max(1, min(8, int(cfg.get("gui.max_concurrent_downloads", 2))))
        )
        self._naming_entry.setText(
            cfg.get("delivery.naming_template", "{title} - Chapter {chapter}")
        )

        self._entry_kindle_email.setText(cfg.get("email.kindle_email", ""))
        self._entry_sender_email.setText(cfg.get("email.sender_email", ""))
        self._entry_smtp_server.setText(cfg.get("email.smtp_server", "smtp.gmail.com"))
        self._entry_smtp_port.setText(str(cfg.get("email.smtp_port", 587)))
        self._password_entry.clear()
        self._delete_after_check.setChecked(cfg.get("delivery.delete_after_send", False))

        self._cron_check.setChecked(cfg.get("cron.enabled", False))
        self._cron_time.setText(cfg.get("cron.time", "06:00"))

        self._post_processing_check.setChecked(
            cfg.get("delivery.post_processing.enabled", False)
        )
        self._post_processing_command.setText(
            cfg.get("delivery.post_processing.command", "")
        )
        self._post_processing_fail_check.setChecked(
            cfg.get("delivery.post_processing.fail_on_error", False)
        )
        self._refresh_post_processing_enabled()

        if hasattr(self, "_partial_check"):
            self._partial_check.setChecked(cfg.partial_enabled)
            self._partial_threshold.setValue(int(round(cfg.partial_threshold)))
            self._partial_threshold.setEnabled(self._partial_check.isChecked())

        if hasattr(self, "_prefetch_check"):
            self._prefetch_check.setChecked(cfg.reader_prefetch_enabled)

        if hasattr(self, "_remove_after_read_check"):
            self._remove_after_read_check.setChecked(
                cfg.get("reader.remove_after_read", False)
            )

        self._refresh_filename_preview()

    def _email_test_inputs(self, need_kindle: bool):
        """The typed settings for an email test as ``(kindle, sender,
        server, port, password, override)``, ``override`` being
        app_password_override()'s result; or None after showing what is
        missing."""
        self._test_label.setToolTip("")
        kindle = self._entry_kindle_email.text().strip()
        sender = self._entry_sender_email.text().strip()
        smtp_server = self._entry_smtp_server.text().strip()
        smtp_port = self._entry_smtp_port.text().strip()
        pw = self._password_entry.text().strip()

        if need_kindle and not kindle:
            self._show_test_status("Fill Kindle email", T.ERROR)
            return None
        if not sender or not smtp_server:
            self._show_test_status("Fill sender + server", T.ERROR)
            return None
        # Issue #247: test the password delivery will use. An injected
        # one wins over the typed field, as it does when sending.
        from ...config import (AppPasswordError, app_password_override,
                               get_app_password)
        try:
            override = app_password_override()
        except AppPasswordError as e:
            self._show_test_status("Password variable unusable", T.ERROR)
            self._test_label.setToolTip(str(e))
            return None
        if override:
            pw = override[1]
            self._test_label.setToolTip(
                f"{override[0]} is set, so it is used instead of the "
                "password field, as when sending.")
        elif not pw:
            pw = get_app_password(self.app.config)
        if not pw:
            self._show_test_status("No password", T.ERROR)
            return None

        # Issue #342: the password must not reach the error details.
        from ...output import register_secret
        register_secret(pw)
        return kindle, sender, smtp_server, smtp_port, pw, override

    def _show_test_status(self, text: str, color) -> None:
        self._test_label.setText(text)
        self._test_label.setStyleSheet(
            f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")

    def _set_email_tests_enabled(self, enabled: bool) -> None:
        # One test at a time: a double click must not send twice.
        self._login_test_btn.setEnabled(enabled)
        self._send_test_btn.setEnabled(enabled)

    def _run_email_test(self, action, success: str, success_detail: str = ""):
        """Run ``action()`` off the UI thread and report its outcome."""
        self._set_email_tests_enabled(False)

        def _test():
            from ...emailer import EmailAuthError, EmailTimeoutError
            try:
                action()
                self._email_test_signals.result.emit(
                    success, "success", success_detail)
            except EmailAuthError as e:
                self._email_test_signals.result.emit("Auth failed", "error", str(e))
            except EmailTimeoutError as e:
                self._email_test_signals.result.emit("Timed out", "error", str(e))
            except Exception as e:
                self._email_test_signals.result.emit(
                    f"Failed: {summarize_error(e, 40)}", "error", str(e))

        threading.Thread(target=_test, daemon=True).start()

    def _test_email(self):
        """Check Login: sign in to the SMTP server; nothing is sent."""
        self._show_test_status("Testing...", T.FG_MUTED)
        inputs = self._email_test_inputs(need_kindle=False)
        if inputs is None:
            return
        _, sender, smtp_server, smtp_port, pw, override = inputs
        if override:
            self._test_label.setText(f"Testing password from {override[0]}...")

        # Issue #361: the same bounded login as delivery and doctor.
        timeout = self.app.config.get("email.smtp_timeout")
        # Issue #366: "auto" picks implicit TLS for a typed port 465.
        smtp_tls = self.app.config.get("email.smtp_tls")

        def _login():
            from ...emailer import smtp_login
            smtp_login(sender, smtp_server, int(smtp_port), pw,
                       timeout=timeout, smtp_tls=smtp_tls)
        self._run_email_test(_login, "Success!")

    def _send_test_email(self):
        """Send Test PDF (issue #365): email a tiny PDF to the typed
        Kindle address the way delivery sends chapters."""
        self._show_test_status("Sending test PDF...", T.FG_MUTED)
        inputs = self._email_test_inputs(need_kindle=True)
        if inputs is None:
            return
        kindle, sender, smtp_server, smtp_port, pw, override = inputs
        if override:
            self._test_label.setText(
                f"Sending test PDF with password from {override[0]}...")
        timeout = self.app.config.get("email.smtp_timeout")
        smtp_tls = self.app.config.get("email.smtp_tls")

        from ...emailer import TEST_DELIVERY_NOTE

        def _send():
            from ...emailer import send_test_document
            send_test_document(kindle, sender, smtp_server, int(smtp_port),
                               pw, timeout=timeout, smtp_tls=smtp_tls)
        self._run_email_test(_send, "Test PDF accepted; check your Kindle",
                             TEST_DELIVERY_NOTE)

    @Slot(str, str, str)
    def _set_email_test_result(self, text: str, kind: str, detail: str = ""):
        self._set_email_tests_enabled(True)
        color = T.SUCCESS if kind == "success" else T.ERROR
        self._show_test_status(text, color)
        if detail and kind == "success":
            # Issue #365: what acceptance means, also in Notifications.
            self._test_label.setToolTip(detail_tooltip(detail))
            notify_error(self.app, "Test PDF accepted by the mail server",
                         detail, ntype="kindle")
        elif detail:
            # Issue #342: the server's full reply, on hover and in
            # Notifications (keyboard and screen-reader reachable).
            self._test_label.setToolTip(detail_tooltip(detail))
            notify_error(self.app, "Email test failed", detail)
            logger.error("Email test failed: %s", detail)

    def _error_toast(self, prefix: str, error) -> None:
        """Issue #342: a short toast; the full error goes to Notifications
        and the (redacted) log."""
        notify_error(self.app, prefix, error)
        logger.error("%s: %s", prefix, error)
        Toast(self, f"{prefix}: {summarize_error(error, 40) or 'Unknown error'}"
                    " (details in Notifications)", kind="error")

    # ── Cron ──

    def _apply_scheduling_capability(self):
        """Turn off installing a scheduled check where this build cannot
        run one (issues #324, #336) and say why. Remove and Status stay
        available so a check set up by an earlier version can still be
        inspected and removed."""
        supported = scheduled_checks_supported()
        reason = "" if supported else SCHEDULING_UNAVAILABLE_TEXT
        for widget in (self._cron_check, self._cron_time,
                       self._cron_install_btn):
            widget.setEnabled(supported)
            widget.setToolTip(reason)
            widget.setAccessibleDescription(reason)
        self._cron_unavailable_hint.setVisible(not supported)

    def _install_cron(self):
        if not scheduled_checks_supported():
            Toast(self, "Scheduled checks need the command-line version",
                  kind="info")
            return
        cron_time = self._cron_time.text().strip()
        if not self._validate_time(cron_time):
            Toast(self, "Invalid time", kind="error")
            return
        hour, minute = cron_time.split(":")

        if platform.system() == "Windows":
            self._install_cron_windows(cron_time)
        else:
            self._install_cron_unix(hour, minute)

    def _explicit_config_dir(self):
        """The --config-dir / $MEMANGA_CONFIG_DIR choice the window runs
        on, pinned into the scheduled check like `memanga cron install`
        does (issue #221); None keeps the default location."""
        return getattr(self.app, "explicit_config_dir", None)

    def _install_cron_unix(self, hour, minute):
        # Issue #232: run the current interpreter and log to the config
        # root, never into the package install directory.
        cron_cmd = build_cron_line(minute, hour, self.app.config.config_dir,
                                   sys.executable,
                                   config_dir=self._explicit_config_dir(),
                                   source_root=source_checkout_root())
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = read_crontab(result)
            if existing is None:
                # Issue #231: never overwrite a crontab we could not read.
                Toast(self, "Could not read crontab; nothing changed", kind="error")
                return
            # Issue #231: only the managed line is replaced.
            proc = subprocess.run(
                ["crontab", "-"], input=replace_managed_line(existing, cron_cmd),
                capture_output=True, text=True
            )
            if proc.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", f"{hour}:{minute}")
                self.app.config.save()
                if unmanaged_memanga_lines(existing):
                    Toast(self, "Cron set; an older MeManga cron line is still "
                          "there, remove it with crontab -e", kind="warning",
                          duration=6000)
                else:
                    Toast(self, f"Cron: daily at {hour}:{minute}", kind="success")
            else:
                self._error_toast("Cron setup failed", proc.stderr)
        except Exception as e:
            self._error_toast("Cron setup failed", e)

    def _install_cron_windows(self, cron_time):
        from .._subprocess import no_window_kwargs
        task_name = "MeManga_AutoCheck"
        # Issue #232: the running interpreter, not a checkout-local venv.
        cmd = build_task_command(sys.executable,
                                 config_dir=self._explicit_config_dir(),
                                 source_root=source_checkout_root())
        try:
            # no_window_kwargs(): release exe is console=False, so any
            # naked subprocess.run() would flash a black cmd box for a
            # frame. schtasks runs headless on a normal admin install,
            # but we still want zero visual noise.
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True, text=True, **no_window_kwargs(),
            )
            result = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/SC", "DAILY",
                 "/ST", cron_time, "/TR", cmd, "/F"],
                capture_output=True, text=True, **no_window_kwargs(),
            )
            if result.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", cron_time)
                self.app.config.save()
                Toast(self, f"Task: daily at {cron_time}", kind="success")
            else:
                self._error_toast("Task setup failed", result.stderr)
        except Exception as e:
            self._error_toast("Task setup failed", e)

    def _remove_cron(self):
        if platform.system() == "Windows":
            from .._subprocess import no_window_kwargs
            try:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", "MeManga_AutoCheck", "/F"],
                    capture_output=True, text=True, **no_window_kwargs(),
                )
                Toast(self, "Task removed", kind="success")
            except Exception:
                Toast(self, "Failed", kind="error")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                # Issue #231: only the managed line is removed; the
                # crontab is not rewritten when there is none.
                new_crontab, removed = remove_managed_lines(existing)
                if removed:
                    proc = subprocess.run(
                        ["crontab", "-"], input=new_crontab,
                        capture_output=True, text=True,
                    )
                    if proc.returncode != 0:
                        self._error_toast("Cron removal failed", proc.stderr)
                        return
                    Toast(self, "Cron removed", kind="success")
                else:
                    # Nothing MeManga owns was removed: keep config as-is,
                    # like `memanga cron remove`.
                    Toast(self, "No managed cron found", kind="info")
                    return
            except Exception:
                Toast(self, "Failed", kind="error")
                return
        self.app.config.set("cron.enabled", False)
        self.app.config.save()
        if not scheduled_checks_supported():
            # The disabled checkbox cannot be unticked by hand; show the
            # removed state (issue #324).
            self._cron_check.setChecked(False)

    def _check_cron_status(self):
        if platform.system() == "Windows":
            from .._subprocess import no_window_kwargs
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", "MeManga_AutoCheck"],
                    capture_output=True, text=True, **no_window_kwargs(),
                )
                text = "Task installed" if result.returncode == 0 else "No task found"
                color = T.SUCCESS if result.returncode == 0 else T.WARNING
            except Exception:
                text, color = "Check failed", T.ERROR
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                found = bool(managed_lines(existing))
                text = "Cron installed" if found else "No cron found"
                color = T.SUCCESS if found else T.WARNING
                if unmanaged_memanga_lines(existing):
                    # Issue #231: lines MeManga does not manage may still run.
                    text += "; unmanaged MeManga line found, edit with crontab -e"
                    color = T.WARNING
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
                "version": EXPORT_VERSION,
                "exported_at": datetime.now().isoformat(),
                "manga": self.app.config.get("manga", []),
                "state": self.app.app_state.get("manga", {}),
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            Toast(self, f"Exported {len(data['manga'])} manga", kind="success")
        except Exception as e:
            self._error_toast("Export failed", e)

    def _import(self, replace=False):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            try:
                data = validate_backup(data)
            except BackupVersionError as exc:
                Toast(self, str(exc), kind="error")
                return
            manga_list = data.get("manga", [])
            if not isinstance(manga_list, list):
                Toast(self, "Invalid file", kind="error")
                return
            if replace:
                self.app.config.set("manga", manga_list)
                self.app.config.save()
                self.app.app_state.set("manga", data.get("state", {}))
                Toast(self, f"Replaced with {len(manga_list)} manga", kind="success")
            else:
                existing = self.app.config.get("manga", [])
                existing_titles = {
                    m.get("title", "").lower(): m.get("title", "")
                    for m in existing
                }
                state_title_aliases = {}
                added = 0
                for m in manga_list:
                    title = m.get("title", "")
                    title_key = title.lower()
                    existing_title = existing_titles.get(title_key)
                    if existing_title is not None:
                        if title != existing_title:
                            state_title_aliases[title] = existing_title
                        continue
                    existing.append(m)
                    existing_titles[title_key] = title
                    added += 1
                self.app.config.set("manga", existing)
                self.app.config.save()
                self.app.app_state.merge_missing_manga_state(
                    data.get("state", {}),
                    merge_existing_downloaded=True,
                    title_aliases=state_title_aliases,
                )
                Toast(self, f"Imported {added} manga", kind="success")
        except json.JSONDecodeError:
            Toast(self, "Invalid JSON", kind="error")
        except Exception as e:
            self._error_toast("Import failed", e)
