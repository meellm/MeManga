"""Issue #340 — when Kindle delivery is on but the output format saves
an image folder (JPG/PNG/WEBP), the chapter is downloaded and delivery
is skipped. The app must tell the user why, as the CLI does.

The handler is exercised unbound on a stub app object, like
test_app_cover_fallback.py: no window or widgets are involved.
"""

from __future__ import annotations

from types import SimpleNamespace


def _handle(stub, data):
    from memanga.gui.app import MeMangaApp
    MeMangaApp._on_kindle_skipped(stub, data)


class TestKindleSkippedNotification:
    def test_adds_warning_with_title_chapter_and_reason(self, state,
                                                        event_bus):
        added = []
        event_bus.subscribe("notification_added", added.append)
        stub = SimpleNamespace(app_state=state, events=event_bus)

        _handle(stub, {
            "task_id": "Vinland Saga:71", "title": "Vinland Saga",
            "chapter": "71", "path": "/downloads/Vinland Saga/Chapter 71",
        })
        event_bus.poll()

        notes = state.get_notifications()
        assert len(notes) == 1
        assert notes[0]["type"] == "warn"
        message = notes[0]["message"]
        assert message.startswith("Not sent to Kindle: Vinland Saga Ch. 71")
        assert "image folders" in message
        assert "PDF, EPUB, CBZ or ZIP" in message
        assert added == [{}]


def _handle_sent(stub, data):
    from memanga.gui.app import MeMangaApp
    MeMangaApp._on_kindle_sent(stub, data)


class TestKindleSentNotification:
    """Issue #338: with delete-after-send on, the notification says what
    happened to the local copy, and never claims a deletion that failed."""

    _SENT = {"task_id": "Vinland Saga:71", "title": "Vinland Saga",
             "chapter": "71", "path": "/downloads/Vinland Saga/ch71.pdf"}

    def _notes(self, state, event_bus, data):
        added = []
        event_bus.subscribe("notification_added", added.append)
        _handle_sent(SimpleNamespace(app_state=state, events=event_bus), data)
        event_bus.poll()
        assert added == [{}]
        notes = state.get_notifications()
        assert len(notes) == 1
        return notes[0]

    def test_sent_without_delete_is_unchanged(self, state, event_bus):
        note = self._notes(state, event_bus, dict(self._SENT))
        assert note["type"] == "kindle"
        assert note["message"] == "Sent to Kindle: ch71.pdf"
        assert "details" not in note

    def test_sent_and_deleted(self, state, event_bus):
        note = self._notes(state, event_bus,
                           {**self._SENT, "local_copy": "deleted"})
        assert note["type"] == "kindle"
        assert note["message"] == "Sent to Kindle: ch71.pdf — local copy deleted"

    def test_sent_but_delete_failed_is_a_warning_with_details(
            self, state, event_bus):
        error = "[Errno 13] Permission denied: 'ch71.pdf'"
        note = self._notes(state, event_bus,
                           {**self._SENT, "local_copy": "kept",
                            "delete_error": error})
        assert note["type"] == "warn"
        assert note["message"].startswith(
            "Sent to Kindle; local copy not deleted: Vinland Saga Ch. 71 - ")
        assert "Permission denied" in note["message"]
        assert "local copy deleted" not in note["message"]
        assert note["details"] == error
