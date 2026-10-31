"""Settings > Kindle / Email: SMTP account, delete-after-send and the
email test controls. The tests themselves run on the page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from ... import theme as T
from ...components.wrapping_label import WrappingLabel


class EmailTabMixin:
    """Builds the Kindle / Email tab into ``self._email_layout``. Its
    buttons call the page's ``_test_email`` and ``_send_test_email``."""

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
        pw_hint = WrappingLabel("(leave blank to keep)")
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
        self._test_hint = WrappingLabel(
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
        self._test_label = WrappingLabel("")
        # Shows a server's reply: never render it as HTML.
        self._test_label.setTextFormat(Qt.TextFormat.PlainText)
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
        f.addWidget(self._test_label)

        # Save button lives in the shared sticky bar at the bottom of
        # the right pane (always visible regardless of scroll position).

    def _show_test_status(self, text: str, color) -> None:
        self._test_label.setText(text)
        self._test_label.setStyleSheet(
            f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")

    def _set_email_tests_enabled(self, enabled: bool) -> None:
        # One test at a time: a double click must not send twice.
        self._login_test_btn.setEnabled(enabled)
        self._send_test_btn.setEnabled(enabled)
