"""Settings > General: appearance, delivery, download folder, output
format, MangaDex quality, concurrent downloads and file naming."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QSizePolicy,
)

from ... import theme as T
from ...components.wrapping_label import WrappingLabel


class GeneralTabMixin:
    """Builds the General tab into ``self._general_layout`` and keeps its
    widgets in sync (Kindle scope, filename preview)."""

    def _build_general(self):
        f = self._general_layout

        # ── Appearance card (theme picker) ──
        # New since the spec rewrite — instantly re-themes the app via
        # the token system. Persisted in QSettings.
        from ...components.theme_picker import ThemePicker
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
        self._scope_hint = WrappingLabel(
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
        from ...components.slider import JumpSlider
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

    def _load_kindle_scope(self):
        from ....email_settings import proposed_kindle_scope
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
        from ....downloader.naming import _format_chapter_number
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
