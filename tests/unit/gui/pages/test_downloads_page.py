"""Downloads page behavior tests."""

from __future__ import annotations

import threading


def _queue_fake_download(app_window, tid="sim-47"):
    app_window.worker._cancel_flags[tid] = threading.Event()
    fake = {
        "task_id": tid,
        "manga": {"title": "T"},
        "chapter": type("C", (), {"number": "1"})(),
        "output_dir": "/tmp",
        "output_format": "pdf",
        "state": None,
        "kindle_cfg": None,
        "naming_template": None,
        "cancel": app_window.worker._cancel_flags[tid],
    }
    app_window.worker._download_queue.append(fake)
    app_window.events.publish(
        "download_queued",
        {"task_id": tid, "title": "T", "chapter": "1"},
    )


def test_cancel_all_disabled_when_empty(app_window, qapp):
    app_window.show_page("downloads")
    qapp.processEvents()
    page = app_window._pages["downloads"]
    assert len(page._active_items) == 0
    assert page._cancel_all_btn.isEnabled() is False

    _queue_fake_download(app_window)
    app_window.events.poll()
    qapp.processEvents()
    assert page._cancel_all_btn.isEnabled() is True

    page._cancel_all()
    app_window.events.poll()
    qapp.processEvents()
    assert len(page._active_items) == 0
    assert page._cancel_all_btn.isEnabled() is False


def test_cancel_all_noop_when_empty(app_window, qapp, monkeypatch):
    import memanga.gui.pages.downloads as downloads_mod

    toasts = []
    monkeypatch.setattr(
        downloads_mod, "Toast", lambda *a, **k: toasts.append((a, k))
    )
    cancelled = []
    app_window.events.subscribe("download_cancelled", cancelled.append)

    page = app_window._pages["downloads"]
    assert len(page._active_items) == 0
    page._cancel_all()
    app_window.events.poll()
    qapp.processEvents()

    assert toasts == []
    assert cancelled == []


def test_cancel_all_confirms_when_cancelling(app_window, qapp, monkeypatch):
    import memanga.gui.pages.downloads as downloads_mod

    toasts = []
    monkeypatch.setattr(
        downloads_mod, "Toast", lambda parent, msg, **k: toasts.append(msg)
    )

    _queue_fake_download(app_window)
    app_window.events.poll()
    qapp.processEvents()

    page = app_window._pages["downloads"]
    page._cancel_all()
    app_window.events.poll()
    qapp.processEvents()

    assert len(app_window.worker._download_queue) == 0
    assert toasts == ["Cancelled all downloads"]


def test_history_shows_kindle_and_deletion_status(app_window, qapp):
    # Issue #338: History says which chapters went to the Kindle and
    # which of those had their local copy deleted afterwards.
    from PySide6.QtWidgets import QLabel

    state = app_window.app_state
    state.add_download_history("Kept", "1", "pdf", "/x/k.pdf", 1.0)
    state.add_download_history("Sent", "2", "pdf", "/x/s.pdf", 1.0, True)
    state.add_download_history("Gone", "3", "pdf", "/x/g.pdf", 1.0, True,
                               deleted_after_send=True)

    app_window.show_page("downloads")
    page = app_window._pages["downloads"]
    page._switch_tab("history")
    qapp.processEvents()

    labels = page._history_content.findChildren(QLabel, "history_delivery")
    # Newest first.
    assert [lbl.text() for lbl in labels] == ["Sent · deleted", "Sent", ""]
    assert [lbl.toolTip() for lbl in labels] == [
        "Sent to Kindle; local copy deleted", "Sent to Kindle", ""]
    assert labels[0].accessibleName() == "Sent to Kindle; local copy deleted"
