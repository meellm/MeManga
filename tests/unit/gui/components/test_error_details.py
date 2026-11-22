"""Issue #342 — short error summaries, the full error details view and
the notification that carries both."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# The real 246-character failure from a refused source connection.
LONG_ERROR = (
    "All sources failed for 'Issue 342 Repro': mangapill.com: "
    "HTTPSConnectionPool(host='127.0.0.1', port=9): Max retries exceeded "
    "with url: /manga/issue-342-repro (Caused by NewConnectionError("
    "\"HTTPSConnection(host='127.0.0.1', port=9): Failed to establish a "
    "new connection: [Errno 111] Connection refused\"))"
)


@pytest.fixture(autouse=True)
def _no_registered_secrets(monkeypatch):
    from memanga import output
    monkeypatch.setattr(output, "_secrets", set())


class TestSummarizeError:
    def test_short_text_unchanged(self):
        from memanga.gui.components.error_details import summarize_error
        assert summarize_error("network down") == "network down"

    def test_long_text_cut_at_a_word_with_ellipsis(self):
        from memanga.gui.components.error_details import summarize_error
        summary = summarize_error(LONG_ERROR, 80)
        assert len(summary) <= 80
        assert summary.endswith("…")
        assert LONG_ERROR.startswith(summary[:-1].rstrip())
        # Never stops inside a word without saying so.
        assert not summary.endswith("hos…")

    def test_single_line(self):
        from memanga.gui.components.error_details import summarize_error
        assert summarize_error("first\n  second\tthird") == "first second third"

    def test_redacts(self):
        from memanga.gui.components.error_details import summarize_error
        assert "hunter22" not in summarize_error("auth password=hunter22")


class TestHelpers:
    def test_has_more_detail(self):
        from memanga.gui.components.error_details import has_more_detail
        assert has_more_detail("Check failed: X - All sources…", LONG_ERROR)
        assert not has_more_detail("Check failed: X - boom", "boom")
        assert not has_more_detail("anything", "")

    def test_tooltip_is_escaped_and_redacted(self):
        from memanga.gui.components.error_details import detail_tooltip
        tip = detail_tooltip("<b>403</b> token=abc")
        assert "<b>" not in tip
        assert "&lt;b&gt;403&lt;/b&gt;" in tip
        assert "abc" not in tip


class TestNotifyError:
    def test_short_message_full_details(self, state, event_bus):
        from memanga.gui.components.error_details import notify_error
        added = []
        event_bus.subscribe("notification_added", added.append)
        app = SimpleNamespace(app_state=state, events=event_bus)

        notify_error(app, "Check failed: Issue 342 Repro", LONG_ERROR)
        event_bus.poll()

        note = state.get_notifications()[0]
        assert note["type"] == "error"
        assert note["message"].startswith("Check failed: Issue 342 Repro - ")
        assert note["message"].endswith("…")
        assert note["details"] == LONG_ERROR
        assert added == [{}]

    def test_secrets_never_stored(self, state, event_bus):
        from memanga import output
        from memanga.gui.components.error_details import notify_error
        output.register_secret("app-pass-1234")
        app = SimpleNamespace(app_state=state, events=event_bus)

        notify_error(app, "Email test failed",
                     "535 login app-pass-1234 for me@example.com rejected")

        note = state.get_notifications()[0]
        for text in (note["message"], note["details"]):
            assert "app-pass-1234" not in text
            assert "me@example.com" not in text


    def test_tooltip_is_bounded(self):
        from memanga.gui.components.error_details import (
            TOOLTIP_CHARS, detail_tooltip)
        tip = detail_tooltip("x" * 5000)
        assert len(tip) < TOOLTIP_CHARS + 100
        assert "more characters cut" in tip

    def test_prefix_is_redacted_and_bounded(self, state, event_bus,
                                            isolated_home):
        # The prefix carries titles and file names; they get the same
        # treatment as the error itself.
        from memanga.gui.components.error_details import (
            PREFIX_CHARS, notify_error)
        app = SimpleNamespace(app_state=state, events=event_bus)
        prefix = (f"Failed: {isolated_home}/Manga/me@example.com "
                  "https://u:hunter22@h.test/x token=abc123 " + "y" * 200)

        notify_error(app, prefix, "boom")

        note = state.get_notifications()[0]
        message = note["message"]
        for leaked in (str(isolated_home), "me@example.com", "hunter22",
                       "abc123"):
            assert leaked not in message
        assert message.startswith("Failed: ~/Manga/***@example.com")
        head, _, tail = message.partition(" - ")
        assert len(head) <= PREFIX_CHARS and head.endswith("…")
        assert tail == "boom"
        assert "details" not in note or "hunter22" not in note["details"]


class TestErrorDetailsDialog:
    def test_shows_full_text_read_only_plain(self, qapp, theme):
        from memanga.gui.components.error_details import ErrorDetailsDialog
        d = ErrorDetailsDialog(None, LONG_ERROR + " <b>x</b>", summary="short")
        assert d._text.toPlainText() == LONG_ERROR + " <b>x</b>"
        assert d._text.isReadOnly()
        assert d._text.tabChangesFocus()
        assert d._text.accessibleName()
        assert d.cancel_btn.text() == "Close"

    def test_copy_puts_redacted_text_on_clipboard(self, qapp, theme,
                                                  isolated_home):
        from PySide6.QtGui import QGuiApplication
        from memanga.gui.components.error_details import ErrorDetailsDialog
        path = isolated_home / "Downloads" / "ch1.pdf"
        d = ErrorDetailsDialog(
            None, f"Permission denied: {path} password=hunter22")
        d._copy_btn.click()
        copied = QGuiApplication.clipboard().text()
        assert copied == d.details
        assert "hunter22" not in copied
        assert str(isolated_home) not in copied
        assert "ch1.pdf" in copied
        assert d._copy_btn.text() == "Copied"

    def test_partial_details_say_so(self, qapp, theme):
        from memanga.gui.components.error_details import ErrorDetailsDialog
        d = ErrorDetailsDialog(None, "start of the error", complete=False,
                               total_chars=250_000)
        assert not d.complete
        assert d._notice is not None
        assert "250,000" in d._notice.text()
        assert "Partial" in d._text.accessibleName()
        assert d._text.accessibleDescription() == d._notice.text()

        whole = ErrorDetailsDialog(None, "boom")
        assert whole.complete and whole._notice is None
        assert whole._text.accessibleName() == "Full error details"

    def test_summary_is_redacted(self, qapp, theme):
        from memanga.gui.components.error_details import ErrorDetailsDialog
        d = ErrorDetailsDialog(None, "boom",
                               summary="Failed: x - password=hunter22")
        assert "hunter22" not in d._summary

    def test_url_user_names_never_reach_state_dialog_or_clipboard(
            self, qapp, theme, state, event_bus):
        # Issue #342: the whole URL userinfo is masked, user name included;
        # host and path stay so the error is still actionable.
        from PySide6.QtGui import QGuiApplication
        from memanga.gui.components.error_details import (
            ErrorDetailsDialog, notify_error)
        app = SimpleNamespace(app_state=state, events=event_bus)
        error = ("HTTPSConnectionPool: 401 for "
                 "https://private-user:pass-1234@feeds.example.com/rss?x=1")
        notify_error(app, "Check failed: https://owner@mirror.example.com/T",
                     error)

        note = state.get_notifications()[0]
        d = ErrorDetailsDialog(None, note["details"], summary=note["message"])
        d._copy_btn.click()
        copied = QGuiApplication.clipboard().text()
        for text in (note["message"], note["details"], d._summary, copied):
            assert "private-user" not in text
            assert "pass-1234" not in text
            assert "owner@" not in text
        assert "https://***@feeds.example.com/rss?x=1" in copied

    def test_custom_partial_notice(self, qapp, theme):
        from memanga.gui.components.error_details import ErrorDetailsDialog
        d = ErrorDetailsDialog(None, "x", complete=False, notice="Cut here.")
        assert d._notice.text() == "Cut here."
        assert d._text.accessibleDescription() == "Cut here."

    def test_close_button_has_accessible_name(self, qapp, theme):
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.components.error_details import ErrorDetailsDialog
        d = ErrorDetailsDialog(None, "boom")
        names = [b.accessibleName() for b in d.findChildren(QPushButton)]
        assert "Close" in names


class TestProgressItemError:
    def test_label_short_full_error_on_hover(self, qapp, theme):
        from PySide6.QtCore import Qt
        from memanga.gui.components.progress_item import ProgressItem
        item = ProgressItem(None, task_id="T:1", title="T", chapter="1")
        item.set_error(LONG_ERROR)
        label = item._status_label
        assert label.text().startswith("Error: ")
        assert label.text().endswith("…")
        assert len(label.text()) <= len("Error: ") + 40
        assert "Connection refused" in label.toolTip()
        assert label.accessibleDescription() == LONG_ERROR
        assert label.textFormat() == Qt.TextFormat.PlainText
