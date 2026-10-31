"""Settings > About: version and environment rows for bug reports and
the Copy diagnostics button. The checks run on the page."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from .... import doctor
from ... import theme as T


class AboutTabMixin:
    """Builds the About tab into ``self._about_layout`` and shows the
    page's ``self._about_info`` in it."""

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
