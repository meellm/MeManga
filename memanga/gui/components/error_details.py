"""
Short error summaries and the full error details view (issue #342).

Toasts, progress labels and notification rows show a concise summary;
the complete error is stored with the notification and opened from the
Notifications page. Everything shown, stored or copied goes through
:func:`memanga.output.redact_diagnostic` first, the notification text
(title or file name included) as well as the error.
"""

import html
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton

from ...output import redact_diagnostic
from .modal import ModalDialog

# Fits one toast or notification line on the default window width.
SUMMARY_CHARS = 80
# The "Check failed: <title>" part of a notification line.
PREFIX_CHARS = 60
# Tooltips are a glance, not the record: the full text is in Notifications.
TOOLTIP_CHARS = 600


def summarize_error(error, limit: int = SUMMARY_CHARS) -> str:
    """One redacted line of at most ``limit`` characters.

    Cuts at a word boundary where one is close and marks the cut with
    "…", so a summary never ends mid-token without saying so.
    """
    text = " ".join(redact_diagnostic(error, limit=None).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def notification_message(prefix, error) -> str:
    """``"<prefix> - <summary>"``, both parts redacted and bounded.

    The prefix carries titles, chapter labels or file names, which can
    hold a path or an address as easily as the error can.
    """
    head = summarize_error(prefix, PREFIX_CHARS) or "Error"
    summary = summarize_error(error) or "Unknown error"
    return redact_diagnostic(f"{head} - {summary}", limit=None)


def notify_error(app, prefix: str, error, ntype: str = "error") -> None:
    """Record a notification with a short message and the full details."""
    app.app_state.add_notification(ntype, notification_message(prefix, error),
                                   details=str(error or ""))
    app.events.publish("notification_added", {})


def detail_tooltip(error) -> str:
    """Redacted error as a tooltip, bounded to ``TOOLTIP_CHARS``.

    Escaped rich text: Qt guesses whether tooltip text is HTML, and only
    rich-text tooltips wrap long lines.
    """
    return f"<p>{html.escape(redact_diagnostic(error, limit=TOOLTIP_CHARS))}</p>"


def has_more_detail(message: str, details: str) -> bool:
    """True when ``details`` says more than the visible ``message``."""
    if not details:
        return False
    return " ".join(details.split()) not in " ".join((message or "").split())


def incomplete_notice(total_chars) -> str:
    """What to tell the user when only part of an error was kept."""
    if isinstance(total_chars, int) and total_chars > 0:
        return (f"Only the first part of this error is shown: it was "
                f"{total_chars:,} characters long and the rest was not kept.")
    return "Only the first part of this error is shown; the rest was not kept."


class ErrorDetailsDialog(ModalDialog):
    """Read-only, selectable view of an error with a Copy action.

    ``complete=False`` means ``details`` is only the start of the error;
    the dialog then says so instead of presenting it as the whole text.
    ``notice`` replaces the default wording of that statement.
    """

    def __init__(self, parent, details: str, summary: str = "",
                 title: str = "Error details", *, complete: bool = True,
                 total_chars=None, notice: Optional[str] = None):
        # Stored details are already bounded; only redact here.
        self._details = redact_diagnostic(details, limit=None)
        self._summary = redact_diagnostic(summary, limit=None)
        self._complete = complete
        self._total_chars = total_chars
        self._notice_text = notice
        super().__init__(parent, title=title, width=560)
        self.setAccessibleName(title)

    def build_body(self):
        self._notice = None
        if not self._complete:
            self._notice = QLabel(self._notice_text
                                  or incomplete_notice(self._total_chars))
            self._notice.setTextFormat(Qt.TextFormat.PlainText)
            self._notice.setWordWrap(True)
            self._notice.setProperty("role", "t2")
            self.body_layout.addWidget(self._notice)

        if self._summary:
            summary = QLabel(self._summary)
            summary.setTextFormat(Qt.TextFormat.PlainText)
            summary.setWordWrap(True)
            summary.setProperty("role", "t2")
            self.body_layout.addWidget(summary)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText(self._details)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Tab leaves the text box instead of being swallowed by it.
        self._text.setTabChangesFocus(True)
        self._text.setMinimumHeight(140)
        self._text.setMaximumHeight(320)
        self._text.setAccessibleName(
            "Full error details" if self._complete else "Partial error details")
        if self._notice is not None:
            self._text.setAccessibleDescription(self._notice.text())
        self.body_layout.addWidget(self._text)

        hint = QLabel("Passwords, tokens, e-mail addresses and your home "
                      "folder are masked in this text and when copied.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        self.body_layout.addWidget(hint)

        self.cancel_btn.setText("Close")
        self._copy_btn = QPushButton("Copy details")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setAccessibleDescription(
            "Copy the error details to the clipboard")
        self._copy_btn.clicked.connect(self._copy)
        self.foot_layout.addWidget(self._copy_btn)

    def showEvent(self, ev):
        super().showEvent(ev)
        # Keyboard users land on the text, ready to select or Tab on.
        self._text.setFocus(Qt.FocusReason.PopupFocusReason)

    @property
    def details(self) -> str:
        return self._details

    @property
    def complete(self) -> bool:
        return self._complete

    def _copy(self):
        QGuiApplication.clipboard().setText(self._details)
        self._copy_btn.setText("Copied")
        self._copy_btn.setAccessibleName("Copied")
        QTimer.singleShot(1500, self._reset_copy_label)

    def _reset_copy_label(self):
        try:
            self._copy_btn.setText("Copy details")
            self._copy_btn.setAccessibleName("")
        except RuntimeError:
            pass  # dialog already closed and deleted
