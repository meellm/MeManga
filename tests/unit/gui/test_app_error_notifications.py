"""Issue #342 — check, download and Kindle delivery failures keep a short
notification message and store the complete error as its details.

The handlers are exercised unbound on a stub app object, like
test_app_kindle_notifications.py: no window or widgets are involved.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

LONG_ERROR = (
    "All sources failed for 'Issue 342 Repro': mangapill.com: "
    "HTTPSConnectionPool(host='127.0.0.1', port=9): Max retries exceeded "
    "with url: /manga/issue-342-repro (Caused by NewConnectionError("
    "\"HTTPSConnection(host='127.0.0.1', port=9): Failed to establish a "
    "new connection: [Errno 111] Connection refused\"))"
)


@pytest.fixture
def stub(state, event_bus):
    return SimpleNamespace(app_state=state, events=event_bus,
                           _settle_new_chapter_download=lambda *a, **k: None)


def _app():
    from memanga.gui.app import MeMangaApp
    return MeMangaApp


class TestCheckError:
    def test_full_error_kept_as_details(self, stub, state):
        _app()._on_check_error(stub, {"title": "Issue 342 Repro",
                                      "error": LONG_ERROR})
        note = state.get_notifications()[0]
        assert note["type"] == "error"
        assert note["message"].startswith("Check failed: Issue 342 Repro - ")
        assert len(note["message"]) < len(LONG_ERROR)
        assert note["details"] == LONG_ERROR
        assert "Connection refused" in note["details"]

    def test_title_in_the_message_is_redacted(self, stub, state,
                                              isolated_home):
        title = f"{isolated_home}/Lib/reader@example.com"
        _app()._on_check_error(stub, {"title": title, "error": "boom"})
        message = state.get_notifications()[0]["message"]
        assert str(isolated_home) not in message
        assert "reader@example.com" not in message
        assert message.startswith("Check failed: ~/Lib/***@example.com")

    def test_correlated_check_adds_nothing(self, stub, state):
        _app()._on_check_error(stub, {"title": "T", "error": LONG_ERROR,
                                      "request_id": 7})
        assert state.get_notifications() == []


class TestDownloadError:
    def test_full_error_kept_as_details(self, stub, state):
        error = ("Could not write '/srv/out/Vinland Saga/Chapter 71.pdf': "
                 "[Errno 28] No space left on device")
        _app()._on_download_error(stub, {"task_id": "Vinland Saga:71",
                                         "title": "Vinland Saga",
                                         "error": error})
        note = state.get_notifications()[0]
        assert note["message"].startswith("Failed: Vinland Saga - ")
        assert note["details"] == error


class TestKindleError:
    def test_send_failure_is_logged(self, stub, caplog):
        with caplog.at_level(logging.ERROR, logger="memanga.gui.app"):
            _app()._on_kindle_error(stub, {"task_id": "Vinland Saga:71",
                                           "error": "SMTP down"})
        assert any(r.getMessage() == "Not sent to Kindle: Vinland Saga Ch. 71: SMTP down"
                   for r in caplog.records)

    def test_send_failure_is_notified_with_details(self, stub, state,
                                                   event_bus):
        added = []
        event_bus.subscribe("notification_added", added.append)
        error = ("(535, b'5.7.8 Username and Password not accepted. "
                 "Learn more at https://support.example.com/mail/?p=BadCredentials')")

        _app()._on_kindle_error(stub, {"task_id": "Vinland Saga:71",
                                       "error": error})
        event_bus.poll()

        note = state.get_notifications()[0]
        assert note["type"] == "error"
        assert note["message"].startswith("Not sent to Kindle: Vinland Saga Ch. 71 - ")
        assert note["details"] == error
        assert added == [{}]

    def test_subscribed(self, app_window):
        handlers = app_window.events._subscribers.get("kindle_error", [])
        assert any(getattr(h, "__func__", None) is _app()._on_kindle_error
                   for h in handlers)
